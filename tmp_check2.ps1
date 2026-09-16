$j = Get-Content 'C:\Users\Victor Suponev\.improve-clauding\runs\20260916-125718\inventory.json' -Raw | ConvertFrom-Json
$sessions = $j.sessions
if (-not $sessions) { $sessions = $j }
$s = $sessions[3]
$s.git | ConvertTo-Json -Depth 5
Write-Output "----"
$s4 = $sessions[4]
$s4.git | ConvertTo-Json -Depth 5
Write-Output "----keys----"
($sessions[3] | Get-Member -MemberType NoteProperty).Name -join ","
