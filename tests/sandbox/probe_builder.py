import subprocess
import sys

def run_probe():
    print("Starting probe...")
    # The dummy batch run is now in orchestrator_pipeline/
    target_file = "orchestrator_pipeline/dummy_batch_run.json"
    try:
        process = subprocess.run(
            [sys.executable, "scripts/builder_agent.py", "--flight-launch-context", target_file],
            timeout=5,
            capture_output=True,
            text=True,
        )
        print("SUCCESS")
        print("STDOUT:", process.stdout)
        print("STDERR:", process.stderr)
    except subprocess.TimeoutExpired as e:
        print("TIMEOUT")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    run_probe()
