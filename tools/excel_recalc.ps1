# Opens a workbook in Excel, recalculates everything, saves a copy (values as Excel computed them).
param([string]$In, [string]$Out, [string]$Macro = "")
$ErrorActionPreference = "Stop"
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
  $wb = $xl.Workbooks.Open($In)
  $xl.CalculateFull()
  if ($Macro -ne "") { $r = $xl.Run($Macro); Write-Output "macro ok: $Macro" }
  $fmt = 51  # xlsx
  if ($Out.EndsWith(".xlsm")) { $fmt = 52 }
  $wb.SaveAs($Out, $fmt)
  $wb.Close($false)
  Write-Output "saved $Out"
} finally {
  $xl.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
}
