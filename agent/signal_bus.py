"""
Universal agent module for RTX Remix game ports.
Provides signal send/receive capabilities and inter-process communication.
"""

import os
import json
import time
import signal as sig_module
from pathlib import Path
from typing import Optional, Callable, Dict, Any

class AgentSignalBus:
    """Signal bus for inter-process communication."""
    
    def __init__(self, repo_name: str = "Substance2Remix"):
        self.repo_name = repo_name
        self.signal_dir = Path(f"/tmp/agent_signals_{repo_name}")
        self.signal_dir.mkdir(exist_ok=True)
        self.handlers: Dict[str, Callable] = {}
        self.running = True
        
        # Register handlers for signals
        sig_module.signal(sig_module.SIGUSR1, self._handle_signal)
        sig_module.signal(sig_module.SIGUSR2, self._handle_signal)
    
    def _handle_signal(self, signum, frame):
        """Handle incoming signals."""
        signal_name = "SIGUSR1" if signum == sig_module.SIGUSR1 else "SIGUSR2"
        print(f"[Agent] Received signal: {signal_name}")
        
        if signal_name in self.handlers:
            self.handlers[signal_name]()
    
    def register_handler(self, signal_name: str, callback: Callable) -> None:
        """Register a callback for a signal."""
        self.handlers[signal_name] = callback
    
    def send_signal(self, target_pid: int, signal_type: str) -> bool:
        """Send signal to another process."""
        try:
            sig = sig_module.SIGUSR1 if signal_type == "SIGUSR1" else sig_module.SIGUSR2
            os.kill(target_pid, sig)
            print(f"[Agent] Sent {signal_type} to PID {target_pid}")
            return True
        except OSError as e:
            print(f"[Agent] ERROR sending signal: {e}")
            return False
    
    def write_message(self, message: Dict[str, Any]) -> str:
        """Write a message file for IPC."""
        msg_file = self.signal_dir / f"msg_{int(time.time() * 1000)}.json"
        msg_file.write_text(json.dumps(message))
        print(f"[Agent] Message written: {msg_file.name}")
        return str(msg_file)
    
    def read_messages(self) -> list:
        """Read all pending messages."""
        messages = []
        for msg_file in sorted(self.signal_dir.glob("msg_*.json")):
            try:
                data = json.loads(msg_file.read_text())
                messages.append(data)
                msg_file.unlink()  # Delete after reading
            except:
                pass
        return messages

def test_signal_bus(repo_name: str = "Substance2Remix") -> Dict[str, Any]:
    """Test signal bus functionality."""
    results = {
        "repo": repo_name,
        "timestamp": time.time(),
        "tests": {}
    }
    
    try:
        # Create signal bus
        bus = AgentSignalBus(repo_name)
        results["tests"]["initialization"] = "PASS"
        
        # Test message writing
        msg = {"type": "test", "content": "Hello from agent"}
        bus.write_message(msg)
        results["tests"]["write_message"] = "PASS"
        
        # Test message reading
        messages = bus.read_messages()
        if messages and messages[0]["type"] == "test":
            results["tests"]["read_message"] = "PASS"
        else:
            results["tests"]["read_message"] = "FAIL"
        
        # Test signal handlers
        bus.register_handler("SIGUSR1", lambda: None)
        results["tests"]["register_handler"] = "PASS"
        
        results["status"] = "OK"
    except Exception as e:
        results["status"] = f"ERROR: {str(e)}"
    
    return results

if __name__ == "__main__":
    import sys
    repo = sys.argv[1] if len(sys.argv) > 1 else "test"
    results = test_signal_bus(repo)
    print(json.dumps(results, indent=2))
