# Keil MDK Compiler Reference

## UV4.exe Command-Line Options

| Option | Description |
|---|---|
| `-b <project>` | Incremental build |
| `-r <project>` | Full rebuild |
| `-c <project>` | Clean |
| `-cr <project>` | Clean before rebuild |
| `-f <project>` | Flash Download |
| `-t <target>` | Specify Target name |
| `-j0` | Suppress UV4 GUI window |
| `-o <logfile>` | Output log to file |

## ERRORLEVEL Exit Codes

| Exit Code | Meaning |
|---|---|
| 0 | No errors, no warnings |
| 1 | Warnings present |
| 2 | Errors present |
| 3 | Fatal error (license / corrupted project, etc.) |
| 11 | Cannot open project file |
| 12 | Device database missing |
| 13 | Write error |
| 15 | UV4 access error (busy, etc.) |
| 20 | Unknown error |

## Common Summary Line Format in Logs

```
".\\Objects\\project.axf" - 0 Error(s), 3 Warning(s).
Program Size: Code=12345 RO-data=678 RW-data=90 ZI-data=1234
```

- **Flash Usage** = Code + RO-data + RW-data
- **RAM Usage** = RW-data + ZI-data

## Common Compilation Error Troubleshooting

| Error Type | Likely Cause |
|---|---|
| `error: #5: cannot open source input file` | File path does not exist or configuration lacks include path |
| `Error: L6218E: Undefined symbol` | Missing source files or libraries during link phase |
| `*** TOOLS.INI: TOOLCHAIN NOT INSTALLED` | Keil toolchain not installed or license issue |
| `*** error 65: access violation` | Flash algorithm does not match target chip |
| `No Algorithm found for` | No Flash algorithm selected in project configuration |
