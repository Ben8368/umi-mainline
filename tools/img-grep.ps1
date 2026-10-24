param([string]$Path,[string]$Needles,[int]$MaxHits = 4,[int]$Ctx = 60)
$enc = [System.Text.Encoding]::GetEncoding(28591)
$t = [System.IO.File]::ReadAllText($Path,$enc)
"file: $Path  chars: $($t.Length)"
foreach($n in ($Needles -split '\|')){
  if(-not $n){ continue }
  $c = 0; $i = 0; $shown = 0
  while(($i = $t.IndexOf($n, $i, [System.StringComparison]::Ordinal)) -ge 0){
    if($shown -lt $MaxHits){
      $a = [Math]::Max(0, $i - $Ctx); $b = [Math]::Min($t.Length, $i + $n.Length + $Ctx)
      $seg = $t.Substring($a, $b - $a) -replace '[^\x20-\x7e]','.'
      "  hit @{0}: {1}" -f $i, $seg
      $shown++
    }
    $c++; $i += $n.Length
  }
  "== [$n] total $c"
}