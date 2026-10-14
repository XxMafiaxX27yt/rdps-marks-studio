param([string]$In)
$ErrorActionPreference = "Stop"
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
  $wb = $xl.Workbooks.Open($In)
  Write-Output ("has VBA project: " + $wb.HasVBProject)
  $xl.Run("RDPS_Recalculate")
  Write-Output ("LastCalc = " + $wb.Names.Item("LastCalc").RefersToRange.Text)
  $xl.Run("RDPS_ResetDashboard")
  Write-Output ("D_Exam = " + $wb.Names.Item("D_Exam").RefersToRange.Text)
  $xl.Run("RDPS_ExportReportCard")
  Write-Output "export ok"
  $wb.Close($false)
} catch {
  Write-Output ("ERROR: " + $_.Exception.Message)
} finally {
  $xl.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
}
