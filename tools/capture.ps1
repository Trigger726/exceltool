# Captures the main window of the running SheetKit process to a PNG.
param(
    [string]$Output = 'tools\_shot.png',
    [int]$WaitSeconds = 15,
    [string]$ProcessName = 'SheetKit'
)

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class SheetKitCapture {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}
"@

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$process = $null
while ((Get-Date) -lt $deadline) {
    $process = Get-Process -Name $ProcessName -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($process) { break }
    Start-Sleep -Milliseconds 200
}

if (-not $process) {
    Write-Output 'NO_WINDOW'
    exit 1
}

$handle = $process.MainWindowHandle
[SheetKitCapture]::ShowWindow($handle, 5) | Out-Null
[SheetKitCapture]::SetForegroundWindow($handle) | Out-Null
Start-Sleep -Milliseconds 2000

$rect = New-Object SheetKitCapture+RECT
[SheetKitCapture]::GetWindowRect($handle, [ref]$rect) | Out-Null
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) {
    Write-Output 'BAD_RECT'
    exit 1
}

$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
$bitmap.Save((Join-Path (Get-Location) $Output), [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
Write-Output "CAPTURED $width x $height -> $Output"
