$j = Get-Content 'C:\Users\Victor Suponev\.improve-clauding\runs\20260916-125718\inventory.json' -Raw | ConvertFrom-Json
$sessions = $j.sessions
if (-not $sessions) { $sessions = $j }
for ($i=0; $i -lt $sessions.Count; $i++) {
  $s = $sessions[$i]
  if ($s.mechanical.on_main_with_commits -eq $true) {
    Write-Output "$i : $($s.title) branch=$($s.branch)"
  }
}
