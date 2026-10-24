param([string]$Path,[string]$Needles)
$enc = [System.Text.Encoding]::GetEncoding(28591)
$t = [System.IO.File]::ReadAllText($Path,$enc)
"file: $Path  chars: $($t.Length)"
foreach($n in ($Needles -split ',')){
  if(-not $n){ continue }
  $c = 0; $i = 0
  while(($i = $t.IndexOf($n, $i, [System.StringComparison]::Ordinal)) -ge 0){ $c++; $i += $n.Length }
  "{0,-30} {1}" -f $n, $c
}