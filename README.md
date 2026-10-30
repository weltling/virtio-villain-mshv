# MSHV UAPI suite

Linux MSHV UAPI tests for partition lifecycle and virtual processor operations.
The suite uses
[Virtio Villain](https://github.com/weltling/virtio-villain)
to run a selected Linux kernel beneath nested Hyper-V through
[Cloud Hypervisor](https://github.com/cloud-hypervisor/cloud-hypervisor)
or [OpenVMM](https://github.com/microsoft/openvmm).
It targets x86-64 parent partitions and child partitions without
isolation.

## Quick start

Use an x86-64 Linux host with working MSHV support for Cloud Hypervisor or
KVM with nested VMX/SVM enabled for OpenVMM. Your user must have read and
write access to `/dev/mshv` or `/dev/kvm` respectively. After changing
device group membership, start a fresh login session. Each test VM uses
two vCPUs and 2 GiB RAM.

Have the following inputs available before starting.

- A current [Virtio Villain](https://github.com/weltling/virtio-villain)
  checkout.
- A compatible VMM executable and its UEFI firmware. Choose either
  [Cloud Hypervisor with MSHV](#cloud-hypervisor-with-mshv) or
  [OpenVMM with KVM](#openvmm-with-kvm) as described below.
- A local Linux source tree with MSHV root partition support, or an existing
  compatible x86-64 `bzImage`.
- The matching [ESP components](#esp-components) in a readable directory.
  Public Azure Linux RPMs provide these files. Follow the
  [download instructions](#download-and-extract-the-boot-packages) below.

Rust and Cargo are needed only if building the VMM.

### 1. Install build and image tools

On Azure Linux, install the native build dependencies and image tools.
The static C library is required to link the test executable.

```sh
sudo tdnf install gcc glibc-devel glibc-static make binutils python3 \
  flex bison bc elfutils-libelf-devel openssl-devel zlib-devel dwarves \
  util-linux dosfstools mtools tar gzip
```

### 2. Select the framework and boot component paths

Run the remaining commands from this repository's root. Replace the example
paths with your checkouts. The boot input directory is separate from the
build output so that `make clean` does not remove downloaded components.

```sh
cd /path/to/virtio-villain-mshv
export VV_ROOT=/path/to/virtio-villain
export MSHV_ESP="$PWD/../mshv-boot-inputs/esp"
```

Populate this directory using the
[public boot packages](#download-and-extract-the-boot-packages).
Select the VMM and its firmware in step 4.

`VV_ROOT` can be omitted when the framework is in a sibling
`virtio-villain` directory.

### 3. Build the appliance and kernel

Build the executable, initramfs and selected kernel in one invocation.
Kernel sources must already be available locally.

```sh
make -j init initramfs kernel MSHV_SOURCE=/path/to/linux
./run --list
```

The default kernel config is `Microsoft/configs/x86/mshv_defconfig` under
`MSHV_SOURCE`. Kconfig adapts this base config to the source tree and local
toolchain. Each changed value is reported with its effective value.
Required appliance options remain strict, including MSHV root partition
support, EFI handover, initramfs support and the serial console.
These requirements are layered from `kernel/common.config` and
`kernel/x86_64.config`.
If using an existing kernel, omit `kernel` and `MSHV_SOURCE`
from the build command. Add `--kernel /path/to/bzImage` to each run command.
An ELF `vmlinux` image cannot be used for this boot path.

Nested testing can hang the outer host. A process timeout cannot recover
that host. Use external recovery for unattended runs.

### 4. Select a VMM and run

Both backends use the same test executable, initramfs, MSHV kernel and
ESP components. They differ in the host hypervisor interface and UEFI
firmware.

| Requirement | Cloud Hypervisor | OpenVMM |
| --- | --- | --- |
| Host interface | `/dev/mshv` | `/dev/kvm` with nested VMX/SVM |
| VMM build | MSHV backend with nested Hyper-V support | KVM backend with `--nested-virt` |
| UEFI firmware | Cloud Hypervisor `CLOUDHV.fd` or compatible firmware | OpenVMM `MSVM.fd` |
| Boot component RPMs | All five packages listed below | All five packages listed below |

#### Cloud Hypervisor with MSHV

Use a Cloud Hypervisor executable built with its `mshv` feature and
support for nested Hyper-V. The host must provide `/dev/mshv` with read
and write access for your user. Ordinary nested VMX/SVM support alone is
not enough for this backend.
See the
[Cloud Hypervisor MSHV guide](https://github.com/cloud-hypervisor/cloud-hypervisor/blob/main/docs/mshv.md).

Obtain `CLOUDHV.fd` from the
[Cloud Hypervisor edk2 releases](https://github.com/cloud-hypervisor/edk2/releases).
This firmware is separate from the ESP component RPMs.

```sh
export MSHV_VMM=/path/to/cloud-hypervisor
firmware=/path/to/CLOUDHV.fd

./run --firmware "$firmware" --offline --console --timeout 180 ML0001
./run --firmware "$firmware" --offline --timeout 180
```

`MSHV_VMM` can be omitted when the correct `cloud-hypervisor` executable
is on `PATH`. Without an explicit firmware path, Cloud Hypervisor uses
the [firmware selection](#firmware) described below.

#### OpenVMM with KVM

Use an OpenVMM build that supports `--nested-virt` on KVM and its matching
`MSVM.fd` UEFI firmware. The host must provide `/dev/kvm` with read and
write access for your user and have nested VMX/SVM enabled. It does not
need `/dev/mshv`.

Cloud Hypervisor firmware is not interchangeable with OpenVMM firmware.
OpenVMM requires an explicit `--firmware` path and does not use the
Cloud Hypervisor firmware download.

```sh
export MSHV_VMM=/path/to/openvmm
firmware=/path/to/MSVM.fd

./run --firmware "$firmware" --offline --console --timeout 180 ML0001
./run --firmware "$firmware" --offline --timeout 180
```

For either backend, the first command runs one lifecycle test with live
console output. The second runs all tests without live VM output.
Both retain complete logs and use local firmware without network access.
The GRUB boot path requires `CONFIG_EFI_STUB=y` and
`CONFIG_EFI_HANDOVER_PROTOCOL=y` in the selected kernel.

The runner selects OpenVMM when the executable name contains `openvmm`.
Use `--backend openvmm` for a renamed executable or `--backend ch` to force
Cloud Hypervisor. `--vmm PATH` overrides `MSHV_VMM` for one run.
Both backends boot the generated ESP disk through UEFI and capture the
serial console.

## Boot inputs

### ESP components

`MSHV_ESP` selects the directory containing the following files from
Azure Linux 3.0 RPMs. Paths are relative to that directory and must match
the filename case shown.

| RPM | Files used by the suite | CH | OpenVMM |
| --- | --- | --- | --- |
| `shim` | `EFI/BOOT/bootx64.efi`, `EFI/BOOT/mmx64.efi` | Required | Required |
| `grub2-efi-binary` | `EFI/BOOT/grubx64.efi` | Required | Required |
| `hvloader` | `HvLoader.efi` | Required | Required |
| `mshv-bootloader-lx` | `lxhvloader.dll` | Required | Required |
| `mshv` | `Windows/System32/hvix64.exe`, `Windows/System32/hvax64.exe`, `Windows/System32/kdstub.dll` | Required | Required |

Keep `mshv` and `mshv-bootloader-lx` at the same version and release.
Both CPU vendor hypervisor binaries are required.
`mshv-kd` is not needed because `mshv` supplies `kdstub.dll`.

Shim and GRUB are requirements of the current shared boot image, not
intrinsic OpenVMM requirements. The suite generates its own boot
configuration. The RPMs are only extracted, not installed on the host.
VMM executables, firmware and the Linux kernel are separate inputs.

#### Download and extract the boot packages

Use `curl` and `bsdtar` to download and extract these x86_64 RPMs.
Run from the suite directory. No repository configuration, package
installation or RPM database is used.

```sh
(
  set -e
  mkdir -p ../mshv-boot-inputs
  cd ../mshv-boot-inputs
  curl -fLO https://packages.microsoft.com/azurelinux/3.0/prod/base/x86_64/Packages/s/shim-16.1-1.azl3.x86_64.rpm
  curl -fLO https://packages.microsoft.com/azurelinux/3.0/prod/base/x86_64/Packages/g/grub2-efi-binary-2.06-27.azl3.x86_64.rpm
  curl -fLO https://packages.microsoft.com/azurelinux/3.0/prod/base/x86_64/Packages/h/hvloader-1.0.1-5.azl3.x86_64.rpm
  curl -fLO https://packages.microsoft.com/azurelinux/3.0/prod/ms-non-oss/x86_64/Packages/m/mshv-26100.9444.2609032029.1-1.azl3.x86_64.rpm
  curl -fLO https://packages.microsoft.com/azurelinux/3.0/prod/ms-non-oss/x86_64/Packages/m/mshv-bootloader-lx-26100.9444.2609032029.1-1.azl3.x86_64.rpm

  mkdir -p root esp
  for package in *.rpm
  do
    bsdtar -xf "$package" -C root
  done
  cp -a root/boot/efi/. esp/
)
export MSHV_ESP="$PWD/../mshv-boot-inputs/esp"
```

`root/boot/efi` is inside the extracted payload, not a host ESP.
The MSHV RPMs are proprietary. Review their license files under
`mshv-boot-inputs/root/usr/share/licenses` before use.

The pinned 26100 set failed before Linux in the checked OpenVMM
configuration. Cloud Hypervisor execution with this set has not been
checked.

### Firmware

For Cloud Hypervisor, without `--firmware`, the runner prefers the installed
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

OpenVMM always requires `--firmware PATH` pointing to its `MSVM.fd`.
The installed Cloud Hypervisor firmware and its download cache are not
used by the OpenVMM backend.

All boot inputs must be nonempty readable regular files. Preflight checks
their formats before launching tests. These checks do not establish
provenance or guarantee that a component set will boot together.

## Build options

The suite currently builds and runs x86_64 appliances only.
`kernel/aarch64.config` provides an ARM64 fragment for kernel configuration
preparation. It requires 4 KiB pages for MSHV and selects the PL011 console.
It does not enable ARM64 appliance builds or execution.

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
Explicit custom configs are checked strictly. The build fails if Kconfig
cannot retain a requested value. A full config from another toolchain may
contain generated compiler versions or unavailable features that need
updating.

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
| `--vmm PATH` | Select Cloud Hypervisor or OpenVMM, overriding `MSHV_VMM` or the default `cloud-hypervisor` command |
| `--backend auto\|ch\|openvmm` | Override backend detection from the executable name |
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
