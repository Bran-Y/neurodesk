REM Independent calculation harness. Original workbook macros are never executed.
Sub Main
  On Error GoTo Failed
  Dim p(3) As New com.sun.star.beans.PropertyValue
  Dim d As Object, s As Object, matrix As Object, cell As Object
  Dim out As Integer, inp As Integer, line As String, fields As Variant
  Dim names As Variant, rows As Variant, i As Integer, j As Integer, text As String
  out = FreeFile
  Open @OUTPUT@ For Output As #out
  p(0).Name = "Hidden": p(0).Value = True
  p(1).Name = "ReadOnly": p(1).Value = True
  p(2).Name = "MacroExecutionMode": p(2).Value = 0
  p(3).Name = "UpdateDocMode": p(3).Value = 0
  d = StarDesktop.loadComponentFromURL(ConvertToURL(@WORKBOOK@), "_blank", 0, p())
  s = d.Sheets.getByName("Statistics")
  matrix = d.Sheets.getByName("Matrix")
  names = Array("Left_Hippocampus", "Right_Hippocampus", "Left_Amygdala", "Right_Amygdala")
  rows = Array(17, 18, 12, 13)
  inp = FreeFile
  Open @INPUT@ For Input As #inp
  Do While Not EOF(inp)
    Line Input #inp, line
    fields = Split(line, ",")
    For j = 0 To 4
      s.getCellByPosition(j+5, 5).Value = CDbl(fields(j+1))
    Next j
    d.calculateAll()
    If Abs(matrix.getCellRangeByName("F2").Value - (CDbl(fields(1))-47.5634617)) > 0.00000001 Then Error 1001
    If Abs(matrix.getCellRangeByName("J2").Value - (CDbl(fields(5))-1521907.28)) > 0.00000001 Then Error 1002
    For i = 0 To 3
      text = fields(0) & "," & names(i)
      For j = 2 To 4
        cell = s.getCellByPosition(j, rows(i))
        If cell.Error <> 0 Or cell.Type <> 3 Then Error 1003
        text = text & "," & Trim(Str(cell.Value))
      Next j
      Print #out, text
    Next i
  Loop
  Close #inp
  s.getCellRangeByName("F6").String = ""
  d.calculateAll()
  For i = 0 To 3
    For j = 2 To 4
      If s.getCellByPosition(j, rows(i)).String <> "-" Then Error 1004
    Next j
  Next i
  Print #out, "#blank_age_guard=passed"
  d.dispose()
  Close #out
  StarDesktop.terminate()
  Exit Sub
Failed:
  Print #out, "#error=" & Err & ": " & Error$
  Close #out
  StarDesktop.terminate()
End Sub
