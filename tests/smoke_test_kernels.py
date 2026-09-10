#!/usr/bin/env python3
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Focused image smoke test for OpenSandbox code-interpreter.

Verifies:
1. HTTP health endpoint and status
2. Installed Jupyter kernelspecs (python, java, tslab, jslab, gonb, bash)
3. Real execution via WebSocket for each kernel:
   - Python: execution and state reuse on the same kernel
   - Java (IJava): execution
   - JavaScript (jslab): execution
   - TypeScript (tslab): execution
   - Go (gonb): execution
   - Bash: execution
"""

import json
import time
import urllib.request
import uuid
import websocket

BASE_URL = "http://127.0.0.1:44771"
WS_URL = "ws://127.0.0.1:44771"
TOKEN = "opensandboxcodeinterpreterjupyter"


def wait_for_health(timeout=30):
    print("==> Checking Jupyter HTTP status...")
    url = f"{BASE_URL}/api/status?token={TOKEN}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    print(f"Jupyter health OK: {data}")
                    return
        except Exception:
            time.sleep(1)
    raise TimeoutError("Jupyter server did not respond with 200 within timeout")


def verify_kernelspecs(timeout=30):
    print("==> Verifying required kernelspecs...")
    url = f"{BASE_URL}/api/kernelspecs?token={TOKEN}"
    required = ["java", "tslab", "jslab", "gonb", "bash"]
    deadline = time.monotonic() + timeout
    installed = []
    while time.monotonic() < deadline:
        with urllib.request.urlopen(url, timeout=5) as resp:
            specs = json.loads(resp.read()).get("kernelspecs", {})
        installed = list(specs)
        if all(name in specs for name in required) and (
            "python" in specs or "python3" in specs
        ):
            print(f"Installed kernelspecs: {installed}")
            return specs
        time.sleep(1)
    raise TimeoutError(f"Required kernels did not become ready; installed: {installed}")


class KernelSession:
    def __init__(self, kernel_name):
        self.kernel_name = kernel_name
        self.kernel_id = None
        self.ws = None

    def __enter__(self):
        url = f"{BASE_URL}/api/kernels?token={TOKEN}"
        payload = json.dumps({"name": self.kernel_name}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            self.kernel_id = data["id"]

        ws_url = f"{WS_URL}/api/kernels/{self.kernel_id}/channels?token={TOKEN}"
        self.ws = websocket.create_connection(ws_url, timeout=30)
        print(f"Connected to {self.kernel_name} kernel ({self.kernel_id})")
        return self

    def execute(self, code, timeout=30):
        msg_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        msg = {
            "header": {
                "msg_id": msg_id,
                "username": "smoke_tester",
                "session": session_id,
                "msg_type": "execute_request",
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": code,
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": False,
            },
            "channel": "shell",
        }
        self.ws.send(json.dumps(msg))

        outputs = []
        errors = []
        completed = False
        reply_status = None
        deadline = time.time() + timeout

        while time.time() < deadline:
            self.ws.settimeout(max(1.0, deadline - time.time()))
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            data = json.loads(raw)
            parent_id = data.get("parent_header", {}).get("msg_id")
            if parent_id != msg_id:
                continue

            msg_type = data.get("msg_type")
            content = data.get("content", {})

            if msg_type == "stream":
                outputs.append(content.get("text", ""))
            elif msg_type == "execute_result":
                text = content.get("data", {}).get("text/plain", "")
                if text:
                    outputs.append(str(text))
            elif msg_type == "error":
                ename = content.get("ename", "")
                evalue = content.get("evalue", "")
                traceback = "\n".join(content.get("traceback", []))
                errors.append(f"{ename}: {evalue}\n{traceback}")
            elif msg_type == "status":
                if content.get("execution_state") == "idle":
                    completed = True
            elif msg_type == "execute_reply":
                reply_status = content.get("status")
            if completed and reply_status is not None:
                break

        full_output = "".join(outputs).strip()
        if not completed or reply_status is None:
            raise TimeoutError(f"[{self.kernel_name}] Execution did not complete: {full_output}")
        if reply_status != "ok":
            errors.append(f"execute_reply status: {reply_status}")
        if errors:
            full_error = "\n".join(errors)
            raise RuntimeError(
                f"[{self.kernel_name}] Execution error: {full_error}\nOutput: {full_output}"
            )
        return full_output

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
        if self.kernel_id:
            try:
                url = f"{BASE_URL}/api/kernels/{self.kernel_id}?token={TOKEN}"
                req = urllib.request.Request(url, method="DELETE")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    pass
            except Exception as e:
                print(f"Warning closing kernel {self.kernel_id}: {e}")


def main():
    wait_for_health(timeout=30)
    specs = verify_kernelspecs()

    # 1. Python: test execution and same-kernel state reuse
    py_kernel = "python" if "python" in specs else "python3"
    print(f"==> Testing {py_kernel} kernel and state reuse...")
    with KernelSession(py_kernel) as session:
        out1 = session.execute('x = 40 + 2\nprint(f"PY_INIT_{x}")')
        print(f"Python step 1 output: {out1}")
        if "PY_INIT_42" not in out1:
            raise AssertionError(f"Expected PY_INIT_42 in output, got: {out1}")

        out2 = session.execute('print(f"PY_STATE_{x + 10}")')
        print(f"Python step 2 output: {out2}")
        if "PY_STATE_52" not in out2:
            raise AssertionError(
                f"Expected PY_STATE_52 in reused state output, got: {out2}"
            )
    print("Python kernel execution & state reuse: PASS")

    # 2. Java
    print("==> Testing Java kernel...")
    with KernelSession("java") as session:
        out = session.execute('System.out.println("JAVA_OUTPUT_" + (100 + 23));')
        print(f"Java output: {out}")
        if "JAVA_OUTPUT_123" not in out:
            raise AssertionError(f"Expected JAVA_OUTPUT_123, got: {out}")
    print("Java kernel: PASS")

    # 3. JavaScript (jslab)
    print("==> Testing jslab kernel...")
    with KernelSession("jslab") as session:
        out = session.execute('console.log("JSLAB_OUTPUT_" + (50 + 5));')
        print(f"jslab output: {out}")
        if "JSLAB_OUTPUT_55" not in out:
            raise AssertionError(f"Expected JSLAB_OUTPUT_55, got: {out}")
    print("jslab kernel: PASS")

    # 4. TypeScript (tslab)
    print("==> Testing tslab kernel...")
    with KernelSession("tslab") as session:
        out = session.execute(
            'const val: number = 70 + 7; console.log("TSLAB_OUTPUT_" + val);'
        )
        print(f"tslab output: {out}")
        if "TSLAB_OUTPUT_77" not in out:
            raise AssertionError(f"Expected TSLAB_OUTPUT_77, got: {out}")
    print("tslab kernel: PASS")

    # 5. Go (gonb)
    print("==> Testing gonb kernel...")
    with KernelSession("gonb") as session:
        go_code = 'import "fmt"\n\nfunc main() {\n\tfmt.Println("GONB_OUTPUT_99")\n}'
        out = session.execute(go_code)
        print(f"gonb output: {out}")
        if "GONB_OUTPUT_99" not in out:
            raise AssertionError(f"Expected GONB_OUTPUT_99, got: {out}")
    print("gonb kernel: PASS")

    # 6. Bash
    print("==> Testing bash kernel...")
    with KernelSession("bash") as session:
        out = session.execute('echo "BASH_OUTPUT_$((10 + 5))"')
        print(f"bash output: {out}")
        if "BASH_OUTPUT_15" not in out:
            raise AssertionError(f"Expected BASH_OUTPUT_15, got: {out}")
    print("bash kernel: PASS")

    print("\n==========================================")
    print("ALL KERNELS PASSED VERIFICATION!")
    print("==========================================")


if __name__ == "__main__":
    main()
