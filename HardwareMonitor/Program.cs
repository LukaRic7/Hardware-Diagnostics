using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using LibreHardwareMonitor.Hardware;

class Program
{
    private static readonly Computer Computer = new Computer
    {
        IsCpuEnabled = true,
        IsGpuEnabled = true,
        IsMemoryEnabled = true,
        IsMotherboardEnabled = true,
        IsNetworkEnabled = true,
        IsStorageEnabled = true,
        IsControllerEnabled = true
    };

    private static readonly int IntervalMs = 1000;

    private static void Main()
    {
        Computer.Open();

        try
        {
            // Discover available sensors and collect their initial values
            var initialMetrics = new Dictionary<string, float>();
            var columns = new HashSet<string>();

            foreach (var hardware in Computer.Hardware)
            {
                DiscoverSensors(hardware, columns, initialMetrics);
            }

            var sensorColumns = columns.OrderBy(x => x).ToList();

            string csvPath = GetCsvPath(sensorColumns);

            Console.WriteLine("Hardware monitor started.");
            Console.WriteLine($"Logging to: {csvPath}");
            Console.WriteLine($"Sensors detected: {sensorColumns.Count}");

            using var writer = new StreamWriter(
                csvPath,
                append: true,
                encoding: new UTF8Encoding(false));

            if (writer.BaseStream.Length == 0)
            {
                var header = new List<string> { "Timestamp" };
                header.AddRange(sensorColumns);

                writer.WriteLine(string.Join(",", header.Select(EscapeCsv)));
                writer.Flush();
            }

            while (true)
            {
                var metrics = new Dictionary<string, float>();

                foreach (var hardware in Computer.Hardware)
                {
                    CollectHardware(hardware, metrics);
                }

                var row = new List<string>
                {
                    DateTimeOffset.Now.ToString(
                        "yyyy-MM-ddTHH:mm:ss.fffzzz",
                        CultureInfo.InvariantCulture)
                };

                foreach (var column in sensorColumns)
                {
                    if (metrics.TryGetValue(column, out float value))
                    {
                        row.Add(value.ToString(
                            "G9",
                            CultureInfo.InvariantCulture));
                    }
                    else
                    {
                        row.Add("");
                    }
                }

                writer.WriteLine(string.Join(",", row));
                writer.Flush();

                Thread.Sleep(IntervalMs);
            }
        }
        finally
        {
            Computer.Close();
        }
    }

    private static void DiscoverSensors(
        IHardware hardware,
        HashSet<string> columns,
        Dictionary<string, float> metrics)
    {
        hardware.Update();

        foreach (var sensor in hardware.Sensors)
        {
            string column = GetSensorColumn(hardware, sensor);

            columns.Add(column);

            if (sensor.Value is float value &&
                !float.IsNaN(value) &&
                !float.IsInfinity(value))
            {
                metrics[column] = value;
            }
        }

        foreach (var subHardware in hardware.SubHardware)
        {
            DiscoverSensors(subHardware, columns, metrics);
        }
    }

    private static void CollectHardware(
        IHardware hardware,
        Dictionary<string, float> metrics)
    {
        hardware.Update();

        foreach (var sensor in hardware.Sensors)
        {
            if (sensor.Value is float value &&
                !float.IsNaN(value) &&
                !float.IsInfinity(value))
            {
                string column = GetSensorColumn(hardware, sensor);
                metrics[column] = value;
            }
        }

        foreach (var subHardware in hardware.SubHardware)
        {
            CollectHardware(subHardware, metrics);
        }
    }

    private static string GetSensorColumn(
        IHardware hardware,
        ISensor sensor)
    {
        return $"{hardware.Name} | {sensor.Name} ({sensor.SensorType})";
    }

    private static string GetCsvPath(List<string> sensorColumns)
    {
        string basePath = Path.Combine(
            AppContext.BaseDirectory,
            "metrics.csv");

        var header = new List<string> { "Timestamp" };
        header.AddRange(sensorColumns);

        string expectedHeader = string.Join(
            ",",
            header.Select(EscapeCsv));

        if (!File.Exists(basePath) ||
            new FileInfo(basePath).Length == 0)
        {
            return basePath;
        }

        // Reuse the existing file only if the sensor layout matches
        string existingHeader = File.ReadLines(basePath).FirstOrDefault() ?? "";

        if (existingHeader == expectedHeader)
        {
            return basePath;
        }

        // Hardware/sensors changed: create a new CSV to avoid misaligned columns
        string newPath = Path.Combine(
            AppContext.BaseDirectory,
            $"metrics_{DateTime.Now:yyyyMMdd_HHmmss}.csv");

        return newPath;
    }

    private static string EscapeCsv(string value)
    {
        if (value.Contains(',') ||
            value.Contains('"') ||
            value.Contains('\n') ||
            value.Contains('\r'))
        {
            return "\"" + value.Replace("\"", "\"\"") + "\"";
        }

        return value;
    }
}