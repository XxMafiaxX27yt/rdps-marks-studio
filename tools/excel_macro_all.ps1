param([string]$In)
$ErrorActionPreference = "Stop"
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
  $wb = $xl.Workbooks.Open($In)
  $t = Get-Date
  $xl.Run("RDPS_ExportAllReportCards")
  Write-Output ("all cards ok in " + [int]((Get-Date) - $t).TotalSeconds + " s")
  $wb.Close($false)
} catch { Write-Output ("ERROR: " + $_.Exception.Message) }
finally { $xl.Quit(); [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null }
