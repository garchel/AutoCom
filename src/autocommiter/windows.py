import subprocess
import sys
import winreg
from pathlib import Path

TASK_NAME = "AutoCommiter"
REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _pythonw_executable() -> Path:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        return pythonw
    return Path(sys.executable)


def _registry_autostart_command() -> str:
    pythonw = _pythonw_executable()
    return f'"{pythonw}" -m autocommiter gui --start-minimized'


def _is_registry_autostart_installed() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, TASK_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def is_autostart_installed() -> bool:
    if not _pythonw_executable().exists():
        return False
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    return _is_registry_autostart_installed()


def _install_registry_autostart() -> None:
    command = _registry_autostart_command()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, command)


def _uninstall_registry_autostart() -> None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, TASK_NAME)
    except FileNotFoundError:
        pass
    except OSError as exc:
        # If value doesn't exist, treat as idempotent
        if "cannot find" in str(exc).lower() or "nao pode" in str(exc).lower():
            return
        raise


def install_autostart() -> None:
    pythonw = _pythonw_executable()

    script = f"""
$ErrorActionPreference = "Stop"
$arguments = "-m autocommiter gui --start-minimized"
$action = New-ScheduledTaskAction -Execute "{pythonw}" -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
try {{
    Register-ScheduledTask -TaskName "{TASK_NAME}" `
      -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Output "OK"
}} catch {{
    Write-Error $_.Exception.Message
    exit 1
}}
"""
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    # Fallback to registry Run key when task scheduler requires elevation (Acesso negado)
    err = (result.stderr or result.stdout or "").lower()
    if "acesso negado" in err or "access is denied" in err or "access denied" in err:
        try:
            _install_registry_autostart()
            return
        except Exception as reg_exc:
            raise RuntimeError(
                "Falha ao criar tarefa agendada (Acesso negado) e "
                f"fallback por registro falhou: {reg_exc}. "
                "Execute o PowerShell como Administrador e tente novamente."
            ) from reg_exc
    raise RuntimeError(
        result.stderr.strip()
        or result.stdout.strip()
        or "Failed to install autostart task."
    )


def uninstall_autostart() -> None:
    script = (
        f'$ErrorActionPreference = "Stop"; '
        f'Unregister-ScheduledTask -TaskName "{TASK_NAME}" -Confirm:$false'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    # Also clean registry fallback (idempotent)
    try:
        _uninstall_registry_autostart()
    except Exception:
        pass
    # schtasks returns error if not found; we treat as idempotent
    if result.returncode == 0:
        return
    err = result.stderr.lower()
    if "cannot find" in err or "nao pode" in err or "não pode" in err or "no task" in err:
        return
    if not is_autostart_installed():
        return
    raise RuntimeError(result.stderr.strip() or "Failed to uninstall autostart task.")
