# Export chosen sheets of a workbook to PDF (one PDF per sheet) to look at the design.
param([string]$In, [string]$OutDir, [string]$Sheets)
$ErrorActionPreference = "Stop"
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
  $wb = $xl.Workbooks.Open($In)
  $xl.CalculateFull()
  foreach ($s in $Sheets.Split(",")) {
    $ws = $wb.Worksheets.Item($s)
    $out = Join-Path $OutDir ("sheet_" + ($s -replace ' ','_') + ".pdf")
    $ws.ExportAsFixedFormat(0, $out)
    Write-Output "pdf $out"
  }
  $wb.Close($false)
} finally {
  $xl.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
}
