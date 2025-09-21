param(
  [int]$TimeoutSec = 5
)

$endpoints = @(
  @{Name='Visualiser';     Url='http://localhost:8090/health'}
  @{Name='API';            Url='http://localhost:8091/health'}
  @{Name='ThingsBoard';    Url='http://localhost:8082/'}
  @{Name='pgAdmin';        Url='http://localhost:5050/'}
  @{Name='Jena Fuseki';    Url='http://localhost:3030/$/ping'}
  @{Name='GraphDB';        Url='http://localhost:7200/'}
  @{Name='Jupyter';        Url='http://localhost:8888/'}
  @{Name='Adminer';        Url='http://localhost:8282/'}
  @{Name='Microservices';  Url='http://localhost:6001/health'}
  @{Name='Rasa';           Url='http://localhost:5005/version'}
  @{Name='Action Server';  Url='http://localhost:5055/health'}
  @{Name='Duckling';       Url='http://localhost:8000/'}
  @{Name='File Server';    Url='http://localhost:8080/health'}
  @{Name='NL2SPARQL';      Url='http://localhost:6005/health'}
  @{Name='Ollama';         Url='http://localhost:11434/api/version'}
)

foreach ($e in $endpoints) {
  try {
    $r = Invoke-WebRequest -Uri $e.Url -TimeoutSec $TimeoutSec -UseBasicParsing
    $body = $r.Content
    if ($body.Length -gt 120) { $body = $body.Substring(0,120) + '...' }
    "{0,-16} {1} {2}  {3}" -f $e.Name, $r.StatusCode, $e.Url, $body
  } catch {
    "{0,-16} FAIL {1}  {2}" -f $e.Name, $e.Url, $_.Exception.Message
  }
}