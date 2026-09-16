$j = Get-Content 'C:\Users\Victor Suponev\.improve-clauding\runs\20260916-125718\inventory.json' -Raw | ConvertFrom-Json
$sessions = $j.sessions
if (-not $sessions) { $sessions = $j }
foreach ($i in 0,3,4,8,13,16,23,24,31) {
  $s = $sessions[$i]
  Write-Output "[$i] title=$($s.title) branch=$($s.git_branch) outcome_pending=$($s.outcome_pending)"
}
