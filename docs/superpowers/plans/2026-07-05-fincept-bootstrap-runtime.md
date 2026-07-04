# Fincept Fork Bootstrap and Embedded Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the independent `newFinceptAgentTerminal` fork, establish a reproducible Windows build, and add a smoke-tested CPython 3.12/pybind11 runtime exposing `fincept_native.runtime.health()` without blocking Qt.

**Architecture:** The Fincept fork remains an independent nested Git repository. A feature-gated `fincept_agent_runtime` static library owns CPython on a dedicated `QThread`; a built-in pybind11 module exposes a narrow native API. This first plan deliberately stops at runtime health and lifecycle—the durable event bus, trading bindings, command/risk pipeline, order lifecycle, position manager, and UI each receive separate follow-on plans.

**Tech Stack:** C++20, Qt 6.8.3, CMake 3.27+, Ninja, MSVC 2022 17.10+, CPython 3.12.13, pybind11 2.13.6, Qt Test, PowerShell, uv.

---

## Scope and follow-on plans

This specification contains multiple independently testable subsystems. Implement them in this order rather than as one change:

1. **This plan:** fork/bootstrap, Python 3.12 toolchain, embedded runtime, native health module.
2. Trading schemas, SQLite journal, transactional outbox, and `TradingEventBus`.
3. Read-only market, instrument, and account bindings with bounded conflation.
4. Portfolio intent contract, `CommandService`, risk pipeline, and paper execution.
5. `OrderLifecycleManager`, `PositionManager`, Zerodha reconciliation, and recovery.
6. Dedicated Agent Trading screen, metrics, replay controls, and kill-switch UI.
7. Zerodha live read-only soak, canary execution, and approved automatic execution.

Do not begin a follow-on subsystem until the preceding plan's acceptance commands pass.

## File map for this plan

All paths below are relative to `D:\projects\new trade`.

**Parent repository**

- Create: `docs/superpowers/plans/2026-07-05-fincept-bootstrap-runtime.md` — this plan.
- Local-only modify: `.git/info/exclude` — ignore the independent nested checkout without touching the user's modified `.gitignore`.

**Nested `newFinceptAgentTerminal` repository**

- Create: `fincept-qt/cmake/AgentPython.cmake` — locate CPython and pybind11; define the runtime library.
- Modify: `fincept-qt/CMakeLists.txt` — feature option, include runtime CMake, link runtime, enable tests.
- Modify: `fincept-qt/CMakePresets.json` — enable runtime in `win-dev`, accept `FINCEPT_PYTHON_ROOT`.
- Create: `fincept-qt/src/agent_runtime/AgentRuntimeStatus.h` — runtime state and health DTO.
- Create: `fincept-qt/src/agent_runtime/AgentNativeModule.h` — force-link declaration.
- Create: `fincept-qt/src/agent_runtime/AgentNativeModule.cpp` — built-in `fincept_native` module.
- Create: `fincept-qt/src/agent_runtime/PythonAgentWorker.h` — worker contract.
- Create: `fincept-qt/src/agent_runtime/PythonAgentWorker.cpp` — interpreter lifecycle on its owning thread.
- Create: `fincept-qt/src/agent_runtime/PythonAgentRuntime.h` — Qt-facing singleton lifecycle API.
- Create: `fincept-qt/src/agent_runtime/PythonAgentRuntime.cpp` — thread ownership and status marshaling.
- Modify: `fincept-qt/src/app/main.cpp` — start after primary-instance selection; stop on shutdown.
- Modify: `fincept-qt/src/python/PythonSetupManager.h` — pin managed Python 3.12.13.
- Modify: `fincept-qt/src/python/PythonSetupManager.cpp` — version-neutral progress text.
- Create: `fincept-qt/tests/CMakeLists.txt` — opt-in Qt Test target.
- Create: `fincept-qt/tests/agent_runtime/test_python_agent_runtime.cpp` — lifecycle and native-module tests.
- Create: `fincept-qt/scripts/dev/check_agent_toolchain.ps1` — reproducible prerequisite check.
- Create: `fincept-qt/scripts/dev/test_agent_runtime.ps1` — configure/build/test wrapper.
- Create: `fincept-qt/docs/agent-runtime.md` — developer contract and troubleshooting.
- Modify: `README.md`, `docs/GETTING_STARTED.md`, `docs/CONTRIBUTING.md`, `docs/ARCHITECTURE.md`, `docs/CPP_CONTRIBUTOR_GUIDE.md` — English source-of-truth Python version and runtime description.

### Task 1: Create the independent Fincept fork checkout

- [ ] **Step 1: Confirm the target does not already contain work**

Run from `D:\projects\new trade`:

```powershell
$target = Resolve-Path . | ForEach-Object { Join-Path $_ 'newFinceptAgentTerminal' }
if (Test-Path -LiteralPath $target) {
    throw "Target already exists: $target"
}
```

Expected: no output and exit code 0. If the directory exists, stop and inspect it; do not delete it.

- [ ] **Step 2: Clone the official repository as the upstream remote**

```powershell
git clone --origin upstream https://github.com/Fincept-Corporation/FinceptTerminal.git newFinceptAgentTerminal
git -C newFinceptAgentTerminal remote -v
```

Expected: only `upstream` fetch/push entries are present.

- [ ] **Step 3: Create the integration branch**

```powershell
git -C newFinceptAgentTerminal switch -c codex/native-agent-runtime
git -C newFinceptAgentTerminal status --short --branch
```

Expected: branch `codex/native-agent-runtime`, clean worktree.

- [ ] **Step 4: Exclude the nested repository locally from the parent**

Append exactly one local exclude entry without editing tracked `.gitignore`:

```powershell
$exclude = '.git/info/exclude'
$entry = '/newFinceptAgentTerminal/'
$lines = @(Get-Content -LiteralPath $exclude -ErrorAction SilentlyContinue)
if ($entry -notin $lines) { Add-Content -LiteralPath $exclude -Value $entry }
git status --short -- newFinceptAgentTerminal
```

Expected: no parent-repository status entry for the nested checkout.

### Task 2: Pin and verify the Windows toolchain

- [ ] **Step 1: Install the required managed Python**

```powershell
uv python install 3.12.13
$python = (uv python find 3.12.13).Trim()
$root = & $python -c "import sys; print(sys.base_prefix)"
Test-Path (Join-Path $root 'Include/Python.h')
Test-Path (Join-Path $root 'libs/python312.lib')
```

Expected: both checks print `True`. Python 3.12.13 is the current security release; Python 3.12.10 was the last python.org release with Windows installers, but uv supplies a managed embeddable build.

- [ ] **Step 2: Write the failing toolchain check first**

Create `newFinceptAgentTerminal/fincept-qt/scripts/dev/check_agent_toolchain.ps1`:

```powershell
param([string]$PythonVersion = '3.12.13')
$ErrorActionPreference = 'Stop'

foreach ($command in @('git', 'cmake', 'ninja', 'uv')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $command"
    }
}
if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw 'MSVC cl.exe is unavailable; run from VS 2022 Developer PowerShell.'
}
if (-not $env:QT_DIR -and -not $env:CMAKE_PREFIX_PATH) {
    throw 'Set QT_DIR or CMAKE_PREFIX_PATH to Qt 6.8.3 MSVC 2022 x64.'
}

$python = (uv python find $PythonVersion).Trim()
$root = (& $python -c 'import sys; print(sys.base_prefix)').Trim()
$header = Join-Path $root 'Include/Python.h'
$library = Join-Path $root 'libs/python312.lib'
if (-not (Test-Path $header)) { throw "Missing Python header: $header" }
if (-not (Test-Path $library)) { throw "Missing Python library: $library" }

[pscustomobject]@{
    PythonExecutable = $python
    PythonRoot = $root
    QtRoot = ($env:QT_DIR ?? $env:CMAKE_PREFIX_PATH)
}
Write-Output "Set for this shell: `$env:FINCEPT_PYTHON_ROOT='$root'"
```

- [ ] **Step 3: Run the check and record the real prerequisite failure**

```powershell
& .\newFinceptAgentTerminal\fincept-qt\scripts\dev\check_agent_toolchain.ps1
```

Expected on the current machine before provisioning: a precise failure for the first missing item (currently CMake, Ninja/MSVC environment, or Qt). Do not weaken the checks.

- [ ] **Step 4: Provision missing prerequisites and rerun**

Install the pinned prerequisites from the Fincept README, launch VS 2022 Developer PowerShell, set `QT_DIR` to Qt 6.8.3 MSVC 2022 x64, then run:

```powershell
$env:FINCEPT_PYTHON_ROOT = (& (uv python find 3.12.13) -c 'import sys; print(sys.base_prefix)').Trim()
& .\newFinceptAgentTerminal\fincept-qt\scripts\dev\check_agent_toolchain.ps1
```

Expected: a table containing Python and Qt roots, exit code 0.

- [ ] **Step 5: Establish the unmodified baseline build**

```powershell
Set-Location newFinceptAgentTerminal\fincept-qt
cmake --preset win-dev -DFINCEPT_BUILD_TESTS=OFF
cmake --build --preset win-dev --target FinceptTerminal
```

Expected: configure and build exit 0 before integration changes. Save the exact upstream commit with `git rev-parse HEAD` in the task notes.

### Task 3: Add the feature-gated embedding build target

- [ ] **Step 1: Add a failing CMake assertion**

In `newFinceptAgentTerminal/fincept-qt/CMakeLists.txt`, immediately after `FINCEPT_DEV_BUILD`, add:

```cmake
option(FINCEPT_ENABLE_AGENT_RUNTIME
    "Embed CPython and expose the native agent API"
    OFF)
```

At the end of configure output, add:

```cmake
message(STATUS "  Agent runtime      : ${FINCEPT_ENABLE_AGENT_RUNTIME}")
```

Set `FINCEPT_ENABLE_AGENT_RUNTIME` to `ON` in the `win-dev` preset and configure:

```powershell
cmake --preset win-dev -DFINCEPT_BUILD_TESTS=ON
```

Expected: configure fails because the runtime target/tests do not exist yet.

- [ ] **Step 2: Create `cmake/AgentPython.cmake`**

```cmake
if(NOT FINCEPT_ENABLE_AGENT_RUNTIME)
    return()
endif()

find_package(Python3 3.12 REQUIRED COMPONENTS Interpreter Development.Embed)
if(NOT Python3_VERSION_MAJOR EQUAL 3 OR NOT Python3_VERSION_MINOR EQUAL 12)
    message(FATAL_ERROR "Agent runtime requires CPython 3.12.x; found ${Python3_VERSION}")
endif()

include(FetchContent)
FetchContent_Declare(pybind11
    GIT_REPOSITORY https://github.com/pybind/pybind11.git
    GIT_TAG v2.13.6
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(pybind11)

add_library(fincept_agent_runtime STATIC
    src/agent_runtime/AgentNativeModule.cpp
    src/agent_runtime/PythonAgentWorker.cpp
    src/agent_runtime/PythonAgentRuntime.cpp)
target_include_directories(fincept_agent_runtime PUBLIC src)
target_link_libraries(fincept_agent_runtime PUBLIC Qt6::Core pybind11::embed)
target_compile_definitions(fincept_agent_runtime PRIVATE
    FINCEPT_AGENT_BUILD_ID="${PROJECT_VERSION}")
```

- [ ] **Step 3: Wire the module into the build**

Before `add_executable(FinceptTerminal ...)`:

```cmake
include(cmake/AgentPython.cmake)
```

After the main `target_link_libraries(FinceptTerminal PRIVATE ...)` block:

```cmake
if(FINCEPT_ENABLE_AGENT_RUNTIME)
    target_link_libraries(FinceptTerminal PRIVATE fincept_agent_runtime)
endif()
```

In `CMakePresets.json`, add under `win-dev.cacheVariables`:

```json
"FINCEPT_ENABLE_AGENT_RUNTIME": "ON",
"Python3_ROOT_DIR": "$env{FINCEPT_PYTHON_ROOT}"
```

- [ ] **Step 4: Reconfigure and retain the expected source-file failure**

```powershell
cmake --preset win-dev -DFINCEPT_BUILD_TESTS=ON
```

Expected: configuration reaches `AgentPython.cmake`, finds Python 3.12 and pybind11, then fails because the three runtime `.cpp` files have not been created. Do not commit this temporarily unbuildable boundary; Task 5 commits it together with its implementation.

### Task 4: Implement the runtime lifecycle using TDD

- [ ] **Step 1: Create the failing Qt test**

Create `fincept-qt/tests/agent_runtime/test_python_agent_runtime.cpp`:

```cpp
#include "agent_runtime/PythonAgentRuntime.h"
#include <QSignalSpy>
#include <QtTest>

using fincept::agent_runtime::AgentRuntimeState;
using fincept::agent_runtime::PythonAgentRuntime;

class PythonAgentRuntimeTest final : public QObject {
    Q_OBJECT
  private slots:
    void starts_loads_native_module_and_stops() {
        auto& runtime = PythonAgentRuntime::instance();
        QSignalSpy spy(&runtime, &PythonAgentRuntime::status_changed);
        runtime.start();
        QTRY_COMPARE_WITH_TIMEOUT(runtime.status().state, AgentRuntimeState::Running, 10000);
        QCOMPARE(runtime.status().python_major, 3);
        QCOMPARE(runtime.status().python_minor, 12);
        QVERIFY(runtime.status().native_module_loaded);
        QVERIFY(runtime.status().last_error.isEmpty());
        runtime.stop();
        QCOMPARE(runtime.status().state, AgentRuntimeState::Stopped);
        QVERIFY(spy.count() >= 2);
    }
};

QTEST_GUILESS_MAIN(PythonAgentRuntimeTest)
#include "test_python_agent_runtime.moc"
```

Create `fincept-qt/tests/CMakeLists.txt`:

```cmake
enable_testing()
find_package(Qt6 REQUIRED COMPONENTS Test)
add_executable(test_python_agent_runtime
    agent_runtime/test_python_agent_runtime.cpp)
target_link_libraries(test_python_agent_runtime PRIVATE
    fincept_agent_runtime Qt6::Test)
add_test(NAME python_agent_runtime COMMAND test_python_agent_runtime)
set_tests_properties(python_agent_runtime PROPERTIES TIMEOUT 20)
```

Run:

```powershell
cmake --preset win-dev -DFINCEPT_BUILD_TESTS=ON
cmake --build --preset win-dev --target test_python_agent_runtime
```

Expected: compile fails because `PythonAgentRuntime.h` does not exist.

- [ ] **Step 2: Create the status contract**

Create `fincept-qt/src/agent_runtime/AgentRuntimeStatus.h`:

```cpp
#pragma once
#include <QMetaType>
#include <QString>

namespace fincept::agent_runtime {
enum class AgentRuntimeState { Stopped, Starting, Running, Stopping, Failed };
struct AgentRuntimeStatus {
    AgentRuntimeState state = AgentRuntimeState::Stopped;
    int python_major = 0;
    int python_minor = 0;
    int python_micro = 0;
    bool native_module_loaded = false;
    QString last_error;
};
}
Q_DECLARE_METATYPE(fincept::agent_runtime::AgentRuntimeStatus)
```

- [ ] **Step 3: Create the worker contract**

Create `fincept-qt/src/agent_runtime/PythonAgentWorker.h`:

```cpp
#pragma once
#include "agent_runtime/AgentRuntimeStatus.h"
#include <QObject>

namespace fincept::agent_runtime {
class PythonAgentWorker final : public QObject {
    Q_OBJECT
  public slots:
    void initialize();
    void shutdown();
  signals:
    void initialized(const AgentRuntimeStatus& status);
    void stopped();
    void failed(const QString& error);
  private:
    bool initialized_ = false;
};
}
```

Create `fincept-qt/src/agent_runtime/PythonAgentWorker.cpp` initially with `initialize()` emitting `failed("not implemented")` and an empty `shutdown()`. Build and confirm the test fails at runtime with state `Failed`, proving the signal path is exercised.

- [ ] **Step 4: Create the Qt-facing runtime**

Create `fincept-qt/src/agent_runtime/PythonAgentRuntime.h`:

```cpp
#pragma once
#include "agent_runtime/AgentRuntimeStatus.h"
#include <QMutex>
#include <QObject>
#include <QThread>

namespace fincept::agent_runtime {
class PythonAgentWorker;
class PythonAgentRuntime final : public QObject {
    Q_OBJECT
  public:
    static PythonAgentRuntime& instance();
    void start();
    void stop();
    AgentRuntimeStatus status() const;
  signals:
    void status_changed(const AgentRuntimeStatus& status);
  private:
    PythonAgentRuntime();
    void set_status(const AgentRuntimeStatus& status);
    mutable QMutex mutex_;
    AgentRuntimeStatus status_;
    QThread thread_;
    PythonAgentWorker* worker_ = nullptr;
};
}
```

Implement `PythonAgentRuntime.cpp` so `start()` allocates the worker, moves it to `thread_`, wires `QThread::started` to `initialize`, and updates status using queued signals. `stop()` must invoke `shutdown` with `Qt::BlockingQueuedConnection`, quit, wait, delete the worker, and publish `Stopped`. Never terminate the thread forcibly.

Use this complete implementation as the starting point:

```cpp
#include "agent_runtime/PythonAgentRuntime.h"
#include "agent_runtime/PythonAgentWorker.h"
#include <QMetaObject>
#include <QMutexLocker>

namespace fincept::agent_runtime {
PythonAgentRuntime& PythonAgentRuntime::instance() {
    static PythonAgentRuntime value;
    return value;
}

PythonAgentRuntime::PythonAgentRuntime() {
    qRegisterMetaType<AgentRuntimeStatus>();
}

AgentRuntimeStatus PythonAgentRuntime::status() const {
    QMutexLocker lock(&mutex_);
    return status_;
}

void PythonAgentRuntime::set_status(const AgentRuntimeStatus& value) {
    {
        QMutexLocker lock(&mutex_);
        status_ = value;
    }
    emit status_changed(value);
}

void PythonAgentRuntime::start() {
    const auto current = status();
    if (current.state != AgentRuntimeState::Stopped) return;

    AgentRuntimeStatus starting;
    starting.state = AgentRuntimeState::Starting;
    set_status(starting);

    worker_ = new PythonAgentWorker;
    worker_->moveToThread(&thread_);
    connect(&thread_, &QThread::started,
            worker_, &PythonAgentWorker::initialize);
    connect(worker_, &PythonAgentWorker::initialized,
            this, [this](const AgentRuntimeStatus& value) { set_status(value); },
            Qt::QueuedConnection);
    connect(worker_, &PythonAgentWorker::failed,
            this, [this](const QString& error) {
                AgentRuntimeStatus failed;
                failed.state = AgentRuntimeState::Failed;
                failed.last_error = error;
                set_status(failed);
            }, Qt::QueuedConnection);
    connect(&thread_, &QThread::finished,
            worker_, &QObject::deleteLater);
    thread_.start();
}

void PythonAgentRuntime::stop() {
    if (!thread_.isRunning()) {
        AgentRuntimeStatus stopped;
        stopped.state = AgentRuntimeState::Stopped;
        set_status(stopped);
        return;
    }
    auto stopping = status();
    stopping.state = AgentRuntimeState::Stopping;
    set_status(stopping);
    QMetaObject::invokeMethod(worker_, "shutdown", Qt::BlockingQueuedConnection);
    thread_.quit();
    thread_.wait();
    worker_ = nullptr;
    AgentRuntimeStatus stopped;
    stopped.state = AgentRuntimeState::Stopped;
    set_status(stopped);
}
} // namespace fincept::agent_runtime
```

- [ ] **Step 5: Run the focused test**

```powershell
cmake --build --preset win-dev --target test_python_agent_runtime
ctest --test-dir build/win-dev -R python_agent_runtime --output-on-failure
```

Expected: test still fails because the embedded module is not implemented; no hang or process crash.

### Task 5: Add the built-in `fincept_native` health module

- [ ] **Step 1: Create the force-link declaration**

Create `fincept-qt/src/agent_runtime/AgentNativeModule.h`:

```cpp
#pragma once
namespace fincept::agent_runtime {
void ensure_agent_native_module_linked();
}
```

- [ ] **Step 2: Define the embedded module**

Create `fincept-qt/src/agent_runtime/AgentNativeModule.cpp`:

```cpp
#include "agent_runtime/AgentNativeModule.h"
#include <pybind11/embed.h>

namespace py = pybind11;
namespace fincept::agent_runtime {
void ensure_agent_native_module_linked() {}
}

PYBIND11_EMBEDDED_MODULE(fincept_native, module) {
    auto runtime = module.def_submodule("runtime");
    runtime.def("health", []() {
        py::dict value;
        value["embedded"] = true;
        value["python_major"] = PY_MAJOR_VERSION;
        value["python_minor"] = PY_MINOR_VERSION;
        value["python_micro"] = PY_MICRO_VERSION;
#ifdef FINCEPT_AGENT_BUILD_ID
        value["application_build_id"] = FINCEPT_AGENT_BUILD_ID;
#else
        value["application_build_id"] = "unknown";
#endif
        return value;
    });
}
```

- [ ] **Step 3: Replace the worker stub with real lifecycle code**

In `PythonAgentWorker::initialize()`:

```cpp
#include "agent_runtime/PythonAgentWorker.h"
#include "agent_runtime/AgentNativeModule.h"
#include <pybind11/embed.h>

namespace py = pybind11;
namespace fincept::agent_runtime {
void PythonAgentWorker::initialize() {
    try {
        ensure_agent_native_module_linked();
        py::initialize_interpreter();
        initialized_ = true;
        auto health = py::module_::import("fincept_native")
                          .attr("runtime").attr("health")().cast<py::dict>();
        AgentRuntimeStatus status;
        status.state = AgentRuntimeState::Running;
        status.python_major = health["python_major"].cast<int>();
        status.python_minor = health["python_minor"].cast<int>();
        status.python_micro = health["python_micro"].cast<int>();
        status.native_module_loaded = health["embedded"].cast<bool>();
        emit initialized(status);
    } catch (const std::exception& error) {
        if (initialized_) {
            py::finalize_interpreter();
            initialized_ = false;
        }
        emit failed(QString::fromUtf8(error.what()));
    }
}
```

In `shutdown()`:

```cpp
void PythonAgentWorker::shutdown() {
    if (initialized_) {
        py::finalize_interpreter();
        initialized_ = false;
    }
    emit stopped();
}
} // namespace fincept::agent_runtime
```

- [ ] **Step 4: Verify the lifecycle test passes repeatedly**

```powershell
cmake --build --preset win-dev --target test_python_agent_runtime
1..5 | ForEach-Object {
    ctest --test-dir build/win-dev -R python_agent_runtime --output-on-failure
    if ($LASTEXITCODE -ne 0) { throw "Iteration $_ failed" }
}
```

Expected: five passes, no leaked process, deadlock, or access violation.

- [ ] **Step 5: Commit runtime lifecycle**

```powershell
git add fincept-qt/CMakeLists.txt fincept-qt/CMakePresets.json fincept-qt/cmake/AgentPython.cmake fincept-qt/src/agent_runtime fincept-qt/tests
git commit -m "feat: embed Python 3.12 agent runtime"
```

### Task 6: Integrate runtime startup and managed Python version

- [ ] **Step 1: Add application lifecycle wiring**

In `fincept-qt/src/app/main.cpp`, add the guarded include:

```cpp
#ifdef FINCEPT_ENABLE_AGENT_RUNTIME
#include "agent_runtime/PythonAgentRuntime.h"
#endif
```

After `TerminalShell::instance().initialise()` and only in the primary-instance path, add:

```cpp
#ifdef FINCEPT_ENABLE_AGENT_RUNTIME
    auto& agent_runtime = fincept::agent_runtime::PythonAgentRuntime::instance();
    agent_runtime.start();
    QObject::connect(&app, &QCoreApplication::aboutToQuit,
                     &agent_runtime, [&agent_runtime]() { agent_runtime.stop(); });
#endif
```

Add `FINCEPT_ENABLE_AGENT_RUNTIME=1` to the runtime target's public compile definitions so the application guard and linked target agree.

- [ ] **Step 2: Update the managed Python pin**

Change `PythonSetupManager::kPythonVersion` to `3.12.13`. Replace user-facing hard-coded `Python 3.11` progress strings with `Python %1` populated from `kPythonVersion`. Update only the English source-of-truth documentation listed in the file map; translation refresh is a later documentation task.

- [ ] **Step 3: Add an application lifecycle test assertion**

Extend the focused test to call `start()` twice and `stop()` twice. Assert the second call in each state is a no-op and no extra interpreter is created.

- [ ] **Step 4: Build the full application and run tests**

```powershell
cmake --preset win-dev -DFINCEPT_BUILD_TESTS=ON
cmake --build --preset win-dev --target FinceptTerminal test_python_agent_runtime
ctest --test-dir build/win-dev -R python_agent_runtime --output-on-failure
```

Expected: full build succeeds; focused test passes.

- [ ] **Step 5: Commit lifecycle integration**

```powershell
git add fincept-qt/src/app/main.cpp fincept-qt/src/python README.md docs
git commit -m "feat: start embedded agent runtime with Fincept"
```

### Task 7: Add repeatable developer verification

- [ ] **Step 1: Create the test wrapper**

Create `fincept-qt/scripts/dev/test_agent_runtime.ps1`:

```powershell
param([string]$Preset = 'win-dev')
$ErrorActionPreference = 'Stop'
$python = (uv python find 3.12.13).Trim()
$env:FINCEPT_PYTHON_ROOT = (& $python -c 'import sys; print(sys.base_prefix)').Trim()

& "$PSScriptRoot/check_agent_toolchain.ps1"
if ($LASTEXITCODE -ne 0) { throw 'Toolchain check failed' }
cmake --preset $Preset -DFINCEPT_BUILD_TESTS=ON
if ($LASTEXITCODE -ne 0) { throw 'Configure failed' }
cmake --build --preset $Preset --target FinceptTerminal test_python_agent_runtime
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
ctest --test-dir "build/$Preset" -R python_agent_runtime --output-on-failure
if ($LASTEXITCODE -ne 0) { throw 'Runtime test failed' }
```

- [ ] **Step 2: Document the runtime contract**

Create `fincept-qt/docs/agent-runtime.md` documenting:

- The dedicated-thread and GIL ownership rule.
- `FINCEPT_ENABLE_AGENT_RUNTIME` and `FINCEPT_PYTHON_ROOT`.
- The exact `fincept_native.runtime.health()` response.
- The prohibition on exposing credentials, raw broker pointers, or arbitrary `QObject` instances.
- The start/stop order and failure behavior.
- Commands to run the toolchain check and focused tests.

- [ ] **Step 3: Run fresh verification**

```powershell
Set-Location D:\projects\new trade\newFinceptAgentTerminal\fincept-qt
& .\scripts\dev\test_agent_runtime.ps1
git status --short
```

Expected: toolchain check, configure, full application build, and focused CTest all exit 0. Git status contains only intended documentation/script changes.

- [ ] **Step 4: Commit developer tooling and docs**

```powershell
git add fincept-qt/scripts/dev fincept-qt/docs/agent-runtime.md
git commit -m "docs: add embedded runtime build verification"
```

## Phase acceptance gate

Run from the nested repository and record the output:

```powershell
Set-Location D:\projects\new trade\newFinceptAgentTerminal\fincept-qt
& .\scripts\dev\test_agent_runtime.ps1
git log --oneline --max-count=4
git status --short
```

The phase is complete only when:

- The upstream baseline and modified full application both build.
- CPython reports major/minor `3.12`.
- `fincept_native.runtime.health()` loads inside the embedded interpreter.
- Five repeated lifecycle tests pass without deadlock or crash.
- Start/stop calls are idempotent.
- Secondary Fincept instances exit without starting Python.
- The runtime shuts down before process exit.
- The nested worktree is clean.
- The parent repository does not track the nested checkout.
