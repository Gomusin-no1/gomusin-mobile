"""Launch synthetic server and browser in the same local execution environment."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

root=Path(__file__).resolve().parents[1]
out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=True)
with (out/'server.log').open('w') as log:
    server=subprocess.Popen([sys.executable,str(root/'tests/serve_settlement_v13_e2e.py'),str(out)],cwd=root,stdout=log,stderr=log)
    try:
        for _ in range(100):
            if server.poll() is not None:raise RuntimeError('Synthetic server exited; see server.log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:5013/health',timeout=1) as response:
                    if response.status==200:break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Synthetic server did not start')
        result=subprocess.run(['node',str(root/'tests/test_settlement_v13_browser.mjs'),str(out)],cwd=root,env=os.environ.copy())
        sys.exit(result.returncode)
    finally:
        server.terminate()
        try:server.wait(timeout=5)
        except subprocess.TimeoutExpired:server.kill();server.wait()
