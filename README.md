# MSHV UAPI suite

Linux MSHV UAPI tests for partition lifecycle and virtual processor operations.
The suite uses Virtio Villain and Cloud Hypervisor to run a selected Linux
kernel beneath nested Hyper-V. It targets x86-64 parent partitions and child
partitions without isolation.

## Quick start

Use an x86-64 Linux host with working MSHV support. Your user must have read
and write access to `/dev/mshv`. After changing device group membership,
start a fresh login session. Each test VM uses two vCPUs and 2 GiB RAM.
Ordinary nested VMX/SVM support alone is not sufficient.

Have the following inputs available before starting.

- A current Virtio Villain checkout.
- A Cloud Hypervisor executable built with its `mshv` feature and support
  for nested Hyper-V. Rust and Cargo are needed only if building the VMM.
  See the [Cloud Hypervisor MSHV guide](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/mshv.md).
- A local Linux source tree with MSHV root partition support, or an existing
  compatible x86-64 `bzImage`.
- The matching [ESP components](#esp-components), either in a readable ESP
  directory or in an archive. These are not included in this repository.
- Compatible UEFI firmware. The `edk2-cloud-hypervisor` package supplies
  `/usr/share/cloud-hypervisor/CLOUDHV_EFI.fd`. Obtain the package from an
  approved package source, or supply a firmware file separately.

### 1. Install build and image tools

On Azure Linux, install the native build dependencies and image tools.
The static C library is required to link the test executable.

```sh
sudo tdnf install gcc glibc-devel glibc-static make binutils python3 \
  flex bison bc elfutils-libelf-devel openssl-devel zlib-devel dwarves \
  util-linux dosfstools mtools tar gzip
```

### 2. Select paths and unpack the ESP components

Run the remaining commands from this repository's root. Replace the example
paths with your checkouts and VMM executable.

```sh
cd /path/to/virtio-villain-mshv
export VV_ROOT=/path/to/virtio-villain
export MSHV_VMM=/path/to/cloud-hypervisor
export MSHV_ESP="$HOME/.local/share/virtio-villain-mshv/esp"

mkdir -p "$MSHV_ESP"
tar -xzf /path/to/mshv-boot-components.tar.gz -C "$MSHV_ESP"

firmware=/usr/share/cloud-hypervisor/CLOUDHV_EFI.fd
```

If the ESP files are already available in a readable directory, set
`MSHV_ESP` to that directory instead of extracting an archive. The ESP
archive contains only the eight boot files, not firmware or build outputs.
Change `firmware` if your firmware file is elsewhere.

`VV_ROOT` can be omitted when the framework is in a sibling
`virtio-villain` directory. `MSHV_VMM` can be omitted when the correct
`cloud-hypervisor` executable is on `PATH`.

### 3. Build and run

Build the executable, initramfs and selected kernel in one invocation.
Kernel sources must already be available locally.

```sh
make -j init initramfs kernel MSHV_SOURCE=/path/to/linux
./run --list

./run --firmware "$firmware" --offline --console --timeout 180 ML0001
./run --firmware "$firmware" --offline --timeout 180
```

The first run selects one lifecycle test with live console output. The second
runs all tests. Both use local firmware without network access.

The default kernel config is `Microsoft/configs/x86/mshv_defconfig` under
`MSHV_SOURCE`. If using an existing kernel, omit `kernel` and `MSHV_SOURCE`
from the build command. Add `--kernel /path/to/bzImage` to each run command.
An ELF `vmlinux` image cannot be used for this boot path.

Nested testing can hang the outer host. A process timeout cannot recover
that host. Use external recovery for unattended runs.

## Boot inputs

### ESP components

`MSHV_ESP` defaults to `/boot/efi`. The selected directory must contain these
readable files with exactly this filename case.

```text
EFI/BOOT/bootx64.efi
EFI/BOOT/grubx64.efi
EFI/BOOT/mmx64.efi
HvLoader.efi
lxhvloader.dll
Windows/System32/hvix64.exe
Windows/System32/hvax64.exe
Windows/System32/kdstub.dll
```

The installed component packages are `shim`, `grub2-efi-binary`, `hvloader`,
`mshv-lxhvloader-fre` and `mshv-fre`. Keep the loader and hypervisor packages
from a matching build. Both CPU vendor hypervisor binaries are required.

The full host ESP and its GRUB configuration are not needed. The suite
generates its own boot configuration for the selected kernel and initramfs.
It does not install or download ESP components, modify the host ESP or
elevate privileges.

### Firmware

Without `--firmware`, the runner prefers the installed
`/usr/share/cloud-hypervisor/CLOUDHV_EFI.fd`. If that file is absent, it
downloads `CLOUDHV.fd` from the latest
[Cloud Hypervisor edk2 release](https://github.com/cloud-hypervisor/edk2/releases/latest)
and verifies the published SHA256. An unreadable or invalid installed file
is an error, not a download trigger.

Use `--firmware PATH` to select a local file explicitly. `--offline`
forbids network access and permits installed firmware or the last verified
cached release. The cache is under
`$XDG_CACHE_HOME/virtio-villain/firmware`, or
`$HOME/.cache/virtio-villain/firmware` when `XDG_CACHE_HOME` is unset.
Online fallback checks for the latest release. Download failures do not
silently select an older version.

All boot inputs must be nonempty readable regular files. Preflight checks
their formats before launching tests. These checks do not establish
provenance or guarantee that a component set will boot together.

## Build options

`make init` builds the static test executable. `make initramfs` builds and
packages it as `/init` and is the default target. `mshv` and
`mshv-initramfs` are aliases for `initramfs`. These targets do not require a
kernel source tree.

`make kernel` requires `MSHV_SOURCE`. It accepts modified source trees and
source archives without Git metadata. The runner uses the image from the
last successful kernel build for the selected output root, unless
`--kernel PATH` overrides it. Execution never builds or downloads a kernel
implicitly.

Default build outputs are under this suite directory.

| Output | Purpose |
| --- | --- |
| `target/mshv/init` | Static test executable |
| `target/mshv/initramfs.cpio.gz` | Test initramfs |
| `target/kernel/images/bzImage-x86_64` | Kernel used by the nested boot path |
| `target/kernel/images/vmlinux-x86_64` | ELF kernel image, not a boot input for this suite |

Use `TARGET=custom` when building and `--build-dir custom` when running to
select matching outputs. Relative output roots are resolved from the suite
directory.

```sh
make -j init initramfs kernel MSHV_SOURCE=/path/to/linux TARGET=custom
./run --build-dir custom --timeout 180 ML0001
```

`./run --build ML0001` rebuilds the executable and initramfs before
execution, but not the kernel. Explicit `--binary` and `--initramfs`
overrides cannot be combined with `--build`.

The same build targets are available from the framework directory with
`make SUITE=/path/to/virtio-villain-mshv initramfs` or
`make SUITE=/path/to/virtio-villain-mshv kernel MSHV_SOURCE=/path/to/linux`.
Use `make help` for all suite build variables.

### Custom kernel configs

`KERNEL_CONFIGS` is an ordered, space separated list of config files and
fragments. A nonempty list replaces the default MSHV config. Later files
override earlier values. Relative paths are resolved from the suite directory.

```sh
make kernel MSHV_SOURCE=/path/to/linux \
  KERNEL_CONFIGS="/path/base.config /path/extra.config" \
  KERNEL_ARGS="--output /path/custom-kernel"
```

`KERNEL_ARGS` adds generic kernel builder options after the standard
arguments. Use a new output directory when changing the source, config or
toolchain. The builder rejects changed inputs in an existing output
directory. Set `V=1` to print build commands.

Kernel builds use `RUSTC=false` by default. For a compatible configuration
requiring Rust, pass `RUSTC=rustc` or another compiler command to Make.
Use `"$VV_ROOT/build-kernel" --help` for all kernel builder options.

Custom configurations must include MSHV root partition support and the
features needed to boot the test initramfs. These include `CONFIG_MSHV_ROOT=y`,
`CONFIG_HYPERV=y`, `CONFIG_HYPERV_VMBUS=y`, `CONFIG_BLK_DEV_INITRD=y`,
`CONFIG_RD_GZIP=y`, `CONFIG_DEVTMPFS=y`, `CONFIG_PROC_FS=y`,
`CONFIG_SYSFS=y`, `CONFIG_BINFMT_ELF=y` and the serial console.

### Cleanup

`make clean` removes the entire selected `TARGET` directory, including
kernel builds, caches and saved results. Keep reusable ESP files and
firmware outside that directory.

## Running tests

Use `./run --list` to list test IDs and descriptions without building.
IDs have a category prefix and four digits and can be supplied in any
letter case. Rebuild after adding or changing tests.

| Prefix | Category | Sources |
| --- | --- | --- |
| ML | Partition lifecycle and related operations | [tests/ml](./tests/ml) |
| MR | Virtual processor registers and state | [tests/mr](./tests/mr) |

Omitting IDs runs all tests. Each test and repetition gets a fresh VM.
The suite boots nested Hyper-V before Linux so that the test kernel can
create child partitions. Direct Linux boot and device node presence alone
do not establish the required parent partition privileges.

```sh
./run --timeout 180 --repeat 3 ML0001 MR0001 MR0003
```

| Option | Effect |
| --- | --- |
| `--vmm PATH` | Override `MSHV_VMM` or the `cloud-hypervisor` command on `PATH` |
| `--kernel PATH` | Select an existing x86-64 `bzImage` |
| `--initramfs PATH` | Select a separate test initramfs |
| `--console`, `-c` | Show live VM output while retaining complete logs |
| `--jobs N`, `-j N` | Limit concurrent VMs, with one as the default |
| `--repeat N` | Repeat the selected tests |
| `--timeout SECONDS` | Set the per test deadline, with 120 seconds as the default |
| `--output PATH` | Use a new diagnostics and runtime artifact directory |
| `--control EXECUTABLE` | Select an external watchdog and recovery control |

Console mode runs one VM at a time regardless of `--jobs`.
Use `./run --help` for all options. From the framework directory, use
`./run --suite /path/to/virtio-villain-mshv` with the same options.

Reports, console logs and boot artifacts are retained under
`target/mshv/results/TIMESTAMP-ID/` by default. `--build-dir` changes the
build root and default results location. `--output` selects an explicit
new directory instead. `results.json` includes individual verdicts, image
hashes, launch arguments and artifact paths. Failed runs also retain
diagnostics.

No external recovery control is supplied by this repository. The control
must survive a hang of the outer host, not merely terminate the VMM.
See the framework's [suite documentation](https://github.com/weltling/virtio-villain/blob/main/docs/suites.md)
for the control interface.

Exit status 0 means the executed tests passed. Status 1 means an assertion
or cleanup failed. Status 2 means infrastructure failed. Missing required
privileges, interfaces or boot results cannot produce a pass or an optional
skip.

## Host checks

Host checks do not boot a VM or establish kernel conformance. Flake8 is
required for lint.

```sh
make selftest
make lint
```
