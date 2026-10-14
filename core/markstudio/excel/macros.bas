Attribute VB_Name = "RDPSMacros"
' RDPS Marks Studio - workbook buttons.
' Python does all the processing; these macros only recalculate, reset the
' dashboard and save report cards as PDF. They never change any marks.
Option Explicit

Private Function Interactive() As Boolean
    Interactive = Application.Visible And Application.Interactive
End Function

Private Function NamedCell(ByVal nm As String) As Range
    Set NamedCell = ThisWorkbook.Names(nm).RefersToRange
End Function

Private Function SafeName(ByVal s As String) As String
    Dim bad As Variant, ch As Variant
    bad = Array("\", "/", ":", "*", "?", """", "<", ">", "|")
    For Each ch In bad
        s = Replace(s, ch, "-")
    Next ch
    SafeName = Trim(s)
End Function

Private Function OutputFolder() As String
    Dim p As String
    p = ThisWorkbook.Path
    If p = "" Then p = CreateObject("WScript.Shell").SpecialFolders("MyDocuments")
    OutputFolder = p
End Function

Public Sub RDPS_Recalculate()
    Application.CalculateFull
    On Error Resume Next
    NamedCell("LastCalc").Value = Format(Now, "dd-mm-yyyy hh:nn")
    On Error GoTo 0
    If Interactive() Then MsgBox "All results, labels and charts are up to date.", vbInformation, "RDPS Marks Studio"
End Sub

Public Sub RDPS_ResetDashboard()
    Dim parts() As String
    parts = Split(CStr(Application.Evaluate("D_Default")), "|")
    If UBound(parts) >= 1 Then
        NamedCell("D_Class").Value = parts(0)
        NamedCell("D_Exam").Value = parts(1)
    End If
    NamedCell("D_Section").Value = "All"
    Application.Calculate
    If Interactive() Then
        ThisWorkbook.Worksheets("Dashboard").Activate
        ActiveWindow.ScrollRow = 1
        ActiveWindow.ScrollColumn = 1
    End If
End Sub

Private Function ExportCard(ByVal folder As String) As String
    Dim ws As Worksheet, nm As String, f As String
    Set ws = ThisWorkbook.Worksheets("Report Card")
    nm = SafeName(CStr(NamedCell("RC_Student").Value) & " - " & CStr(NamedCell("RC_Exam").Value))
    f = folder & "\" & nm & ".pdf"
    ws.ExportAsFixedFormat Type:=0, Filename:=f, Quality:=0, IncludeDocProperties:=False, _
        IgnorePrintAreas:=False, OpenAfterPublish:=False
    ExportCard = f
End Function

Public Sub RDPS_ExportReportCard()
    Dim f As String
    Application.Calculate
    f = ExportCard(OutputFolder())
    If Interactive() Then MsgBox "Saved:" & vbCrLf & f, vbInformation, "RDPS Marks Studio"
End Sub

Public Sub RDPS_ExportAllReportCards()
    Dim labels As Range, c As Range, keep As String, folder As String, n As Long, has As Variant
    Set labels = ThisWorkbook.Names("L_StudentLabels").RefersToRange
    keep = CStr(NamedCell("RC_Student").Value)
    folder = OutputFolder() & "\" & SafeName("Report Cards - " & CStr(NamedCell("RC_Exam").Value))
    If Dir(folder, vbDirectory) = "" Then MkDir folder
    Application.ScreenUpdating = False
    On Error GoTo done
    For Each c In labels.Cells
        If CStr(c.Value) <> "" Then
            NamedCell("RC_Student").Value = c.Value
            Application.Calculate
            has = Application.Evaluate("COUNTIF(MX_Key,RC_ID&""|""&RC_Exam)")
            If Not IsError(has) Then
                If has > 0 Then
                    ExportCard folder
                    n = n + 1
                    Application.StatusBar = "Saving report cards... " & n
                End If
            End If
        End If
    Next c
done:
    NamedCell("RC_Student").Value = keep
    Application.Calculate
    Application.StatusBar = False
    Application.ScreenUpdating = True
    If Interactive() Then MsgBox n & " report cards saved in:" & vbCrLf & folder, vbInformation, "RDPS Marks Studio"
End Sub
