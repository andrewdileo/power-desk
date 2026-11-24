# Power Desk V1

Native Windows power-control app with an original Stella-style interface.

## Open

Requires Windows 10/11 x64 and Python 3.11+.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

After setup, double-click `Open-Power-Desk.bat`. It prefers the local virtual environment, then an existing per-user Anaconda installation, then the Windows Python launcher. No installer, background service or startup task is added.

NVIDIA GPU telemetry additionally requires an installed driver exposing `nvidia-smi` on PATH. Other Windows controls remain usable without it. This is an experimental V1; backend tests and a local hardware check do not certify every motherboard or driver.

## Controls

- Modes: Quiet, Everyday, Create and Render. Moving the slider previews; Apply performs the change.
- Advanced: AC CPU minimum/maximum, energy preference, boost policy, display timeout, sleep timeout, disk idle and PCIe link savings. Windows values are read back after applying. Battery settings inherit the Balanced base; they are shown in the active settings readout.
- Optional NVIDIA power cap uses the detected GPU UUID and limits its range to the factory default. Tested RTX 5090 telemetry works; writes returned Insufficient Permissions in the standard session. Opening the app never elevates privileges automatically.
- Energy audit: live GPU watts, temperature and utilization, watt trace, sampled average/peak, integrated GPU Wh and cost estimate, CSV export. CPU package and wall/PSU watts are explicitly unavailable; no fictional total-power estimate. This does not benchmark energy efficiency automatically.
- Automation: editable/saved process-name rules, 30-second stable detection and 60-second cooldown; highest matching mode wins. Disabled by default. Manual Apply disables automation; auto rules leave GPU caps unchanged. Runs only while the app is open.
- Commands: command preview, action log and PowerShell script export. CLI supports `--apply Quiet`, `--restore`, `--inspect`, and `--audit-seconds 60 --csv audit.csv`. PowerShell entry points are generated using the actual Python/app paths. Scripts respect existing PowerShell execution policy.

## Persistence and restore

App state, original-plan JSON snapshot, command history, audit-session CSV and saved rules live in `%LOCALAPPDATA%\PowerDesk`. The original Windows plan is never edited. Each Apply creates a new Balanced-based plan, configures it, verifies values and activates it. Failed preparation leaves the current plan unchanged. Restore original settings reactivates the saved original plan and restores a GPU limit if this app changed it. Closing the app leaves the selected power plan active. Managed plans are retained rather than deleting Windows settings.

A native `.pow` export was denied by the current session's privileges; the JSON backup and untouched original plan were verified instead. If an original plan is deleted outside this app, restoration must be handled manually; no hidden import/elevation is attempted. CPU performance-state controls depend on hardware and should be measured against actual task duration. A 400 W GPU ceiling does not mean 400 W idle consumption.

## Validation

- Five backend tests passed: validation, energy integration/gap exclusion, preparation failure, GPU permission failure, and restore/no-unrequested-GPU-write behavior.
- Real Quiet profile application verified all eight AC settings, then restored the original Ultimate Performance plan.
- GPU power reads work; writing the unchanged 575 W ceiling was denied by the driver for insufficient permissions.
- GUI reviewed live; diagnostic CSV capture verified. No BIOS, voltage, fan, PSU, registry security or driver model changes.

## Sensor reference

CPUID HWMonitor is installed and can be opened from the Audit tab. Its proprietary monitoring SDK is not bundled or scraped. See https://www.cpuid-pro.com/products-system-monitoring-kit.php . NVIDIA readings/control use https://docs.nvidia.com/deploy/nvidia-smi/index.html . Windows plan operations follow https://learn.microsoft.com/en-us/windows-hardware/design/device-experiences/powercfg-command-line-options .

## Development

```powershell
python -m unittest discover -s . -p "test_backend.py" -v
python -m py_compile app.py backend.py
```

Windows CI runs these checks. Automated tests mock control commands; they do not change CI power plans or GPU settings. Local sensor logs, verification artifacts and environment files are excluded from version control.
