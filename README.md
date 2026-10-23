# Private MSHV UAPI suite

This directory is intentionally outside the public Virtio Villain repository.
It contains all code and policy specific to MSHV. Virtio Villain provides the
generic registration, assertions, guest runner, initramfs build and host
orchestration. This suite uses that framework rather than a separate copy.

The local repository versions only source, tests, build files and documentation.
Build outputs, generated ABI headers, kernel images and caches under `target`
are not versioned. No remote repository is configured.

The suite requires the generic appliance interfaces in `~/virtio-villain`.
The initial framework series ends at commit `eda443e`. Earlier framework
revisions do not provide these interfaces.

Virtio Villain builds the appliance and supplies guest registration,
assertions and test execution. Its host runner owns selection, supervision
and reporting. This repository supplies the MSHV cases and launch policy.

## Selected contract

- Full source: `~/linux`.
- Branch inspected: `feature/linux-mshv/6.18`.
- Commit: `d461acfb591c198755f6e84494f8a68a3b6d8bd2`.
- Configuration: `Microsoft/configs/x86/mshv_defconfig` from that source.
- Architecture: x86-64, child partitions without isolation, VP index 0 initially.

The ABI generator requires this exact commit with no tracked source changes.
It extracts the tested structures and IOCTL definitions from
`include/uapi/linux/mshv.h`, not the headers installed on the host. Register
association layout follows `include/hyperv/hvgdk_mini.h`. The packed
association is 32 bytes with a 16 byte value at offset 16. Reserved fields
are zero. General purpose
register identifiers follow the Hyper-V TLFS x64 register namespace.

`drivers/hv/mshv_root_main.c` establishes:

- Create partition returns an `FD_CLOEXEC` descriptor but does not initialize
  the partition. Call `MSHV_INITIALIZE_PARTITION` before creating the VP.
- Repeated initialization returns zero.
- `MSHV_CREATE_VP` returns a usable `FD_CLOEXEC` descriptor.
- The VP holds a partition reference. Closing the device and partition
  descriptors permits continued VP register access.
- Closing a VP descriptor does not remove the VP from the partition VP array.
  Recreating that index returns `EEXIST`. Another index can still be created.
- The retained compatibility register IOCTLs return `EINVAL` for count >128.
  NULL request pointers and NULL arrays with nonzero count return `EFAULT`.
  SET of explicit/intercept suspend registers returns `EINVAL`.

The compatibility IOCTLs are deprecated but remain implemented in this exact
contract. Their unexpected absence is a failed assertion, not an optional skip.

Only RAX, RCX, RDX and RBX are written. Their complete 64-bit values are compared,
including all ones and values with high bits set. They have no architectural reserved
bits requiring normalization. The upper 64 bits of the 128-bit ABI value
slot are not asserted for 64-bit registers. Reserved association fields are
zeroed. No mixed valid/invalid batch is used and no rollback/atomicity
guarantee is inferred.

## Execution environment

The kernel executing the IOCTLs must run as a Hyper-V parent partition.
It must be a root partition or appropriately provisioned L1VH without
isolation and with `CreatePartitions`
privilege. The selected kernel checks CPUID `0x40000003`, EBX bit 0 (and excludes
isolated guests) before enabling its parent partition path. `CPUManagement`
distinguishes a root partition from L1VH. It is not required by this suite.

The appliance checks CPUID, then actually creates, initializes and closes a
partition and VP before running assertions. Device node presence alone is
insufficient. The host VMM process also needs read/write access to its
`/dev/mshv`. Use a fresh login or process with updated group membership.

Required appliance kernel features built into the image include `CONFIG_MSHV_ROOT=y`,
`CONFIG_HYPERV=y`, `CONFIG_HYPERV_VMBUS=y`, `CONFIG_BLK_DEV_INITRD=y`,
`CONFIG_RD_GZIP=y`, `CONFIG_DEVTMPFS=y`, `CONFIG_PROC_FS=y`, `CONFIG_SYSFS=y`,
`CONFIG_BINFMT_ELF=y`, and the serial console. The Microsoft configuration
already supplies these. It is not replaced by a minimal custom profile.

### Nested feasibility status

The validated model is host VMM -> nested Hyper-V -> selected Linux test
appliance -> partitions created by the UAPI tests. Ordinary nested VMX/SVM
support is not sufficient.

- Local Cloud Hypervisor `bb5f54912e45f3b9878d0e8e4c8884bd4b4bf21b` implements
  `--cpus nested=on` in its MSHV backend, setting the nested partition creation
  flag and enabling the nested processor feature.
- Local OpenVMM `54e06dc641735d6019f02135938607b4aa2c0f65` implements nested
  virtualization for WHP/KVM, but its MSHV backend reports it unsupported.
- TMK uses the MSHV backend on the host to run a bare metal payload. It does not
  supply a Linux kernel UAPI inside the payload and is not a replacement for
  this appliance.

Direct Linux boot with local Cloud Hypervisor commit
`bb5f54912e45f3b9878d0e8e4c8884bd4b4bf21b` reached the appliance entry point
on the selected kernel and shut down cleanly. CPUID `0x40000003` returned
EBX `0x00020000`. The `CreatePartitions` bit was absent, so preflight reported
an infrastructure failure without executing any assertions.

Thus `nested=on` alone is not enough to run these UAPI tests.
Do not bypass the privilege check or change the expected test results.
The suite uses the nested Hyper-V boot image described below to supply
the required environment.
Actual child partition creation and all seven UAPI tests passed with it.

## Build

Dependencies on Azure Linux include GCC, glibc-devel, glibc-static, make,
binutils, Python 3, flex, bison, bc, elfutils-libelf-devel, openssl-devel,
zlib-devel and dwarves. Flake8 is required for lint. Rust/Cargo are useful
for rebuilding VMMs but are not needed to compile the C test executable.

```sh
cd ~/virtio-villain-mshv
make -j init initramfs
make kernel
make selftest lint
./run-mshv --list
```

`init` builds the test executable. `initramfs` builds and packages it.
Requesting both with `-j` builds the executable once before packaging.
The default target is `initramfs`. The existing `mshv` and `mshv-initramfs`
names remain aliases for the complete archive build.

`VV_ROOT`/`MSHV_SOURCE` Make variables select alternate framework/source trees.
The wrapper also accepts `VV_ROOT` as an environment variable. All suite and
kernel outputs are beneath `target` in this directory, not the public repo.

The kernel target disables Rust compiler probing to match the selected
Microsoft C configuration, even when Rust is installed for VMM development.
No extra command line setting is required. No kernel configuration options
are silently discarded. The kernel build uses all available CPU cores.

Use `make help` to list targets, config selection and build variables.
From the framework directory, use `make -C ../virtio-villain-mshv help`.
Execution options are listed by `./run --suite ../virtio-villain-mshv --help`
from the framework directory.

### Custom kernel configs

`KERNEL_CONFIGS` is a space separated list of config files and fragments.
An empty list uses `$(MSHV_SOURCE)/Microsoft/configs/x86/mshv_defconfig`.
A nonempty list replaces that default. Include the Microsoft config
explicitly when applying fragments to it. Later files override earlier values.
Relative paths are resolved from the suite directory.

For example, from the framework directory:

```sh
make -C ../virtio-villain-mshv kernel \
  KERNEL_CONFIGS="$HOME/linux/Microsoft/configs/x86/mshv_defconfig /path/extra.config" \
  KERNEL_ARGS="--output /path/custom-kernel --jobs 8"
```

`KERNEL_ARGS` adds builder options after the standard arguments. Any additional
`--config` options are applied last. Use a new output directory when changing
the source, config or toolchain. The builder rejects changed inputs in an
existing output directory instead of silently reusing them.

The selected Microsoft config uses `RUSTC=false` by default. For a compatible
custom config requiring Rust, set `RUSTC=rustc` or another compiler command.
Config validation remains strict.

Select a custom kernel image at execution:

```sh
./run --suite ../virtio-villain-mshv \
  --kernel /path/custom-kernel/images/bzImage-x86_64
```

### Build outputs

Outputs:

- `target/mshv/init`: static executable, packaged as `/init`.
- `target/mshv/initramfs.cpio.gz`: separate reproducible archive.
- `target/kernel-microsoft/images/vmlinux-x86_64`: Cloud Hypervisor ELF image.
- `target/kernel-microsoft/images/bzImage-x86_64`: compressed Linux image.
- Adjacent config, hashes and generic kernel builder provenance metadata.

## Run

### Nested Hyper-V boot image

The suite starts a second Hyper-V instance before Linux. Direct Linux boot
does not grant the required parent privileges. The suite constructs a
separate UEFI boot disk from the installed components for each test.
To build a disk separately:

```sh
python3 lib/boot_image.py --output target/nested-hyperv/appliance
```

The builder reads the host ESP and copies the installed shim, GRUB and
Hyper-V loaders. It also copies both CPU vendor hypervisor binaries and
`kdstub.dll`. All inputs must be readable by the current user. The builder
never elevates privileges. Use `--esp PATH` to select a readable copy of
the ESP components, or set `MSHV_ESP` for both the builder and suite.
No host boot files or firmware settings are modified. No additional boot
components are downloaded or installed.

The output directory contains `boot.img`, `firmware.fd`, `grub.cfg` and
`manifest.json`. The manifest records source paths and hashes. Temporary
assembly files live under `target/image-work/assemble-*` and are removed
after construction. Choose a new output directory for another build.

The disk has a GPT EFI System Partition. Its boot sequence is firmware,
shim, GRUB, Hyper-V and then the selected kernel with the test initramfs.
The GRUB entry follows the installed host sequence without copying its
root device identifiers or enabling AMD confidential guest options.

Run the suite through the same shared framework:

```sh
~/virtio-villain/run \
  --suite ~/virtio-villain-mshv \
  --timeout 120 --jobs 16
```

The suite selects the nested boot environment automatically. It uses the
neighboring Cloud Hypervisor build with `nested=on`. Use `--vmm PATH` or set
`MSHV_VMM` to select another Cloud Hypervisor binary. This boot path requires
`bzImage`, not an ELF `vmlinux` image.

The suite uses `target/kernel-microsoft/images/bzImage-x86_64` from its own
directory by default. Build it with `make kernel`. Use
`--kernel PATH` to select another image, including output from a custom
`TARGET`. Missing or empty images are infrastructure errors. The runner
does not download or build a kernel implicitly.

An initial nested Hyper-V boot reached the selected kernel. Guest CPUID
`0x40000003` returned EBX `0x002bb9ff`. Preflight created a child partition
and VP, and `ML001` returned PASS. The kernel then hit a BUG in
`hv_machine_power_off` during shutdown. The launcher timed out, so the
overall run was an infrastructure failure.

The suite now uses explicit host controlled shutdown. After tests release
their resources and report results, the guest synchronizes and signals that
it is ready to stop. The runner validates the results and stop marker before
terminating Cloud Hypervisor. The guest does not enter the broken poweroff
path. This tests UAPI operation, not the kernel poweroff implementation.
All seven lifecycle and register tests passed in separate nested Hyper-V
boots on 2026-10-22 using this shutdown mode. Each guest completed its
result protocol and stop handshake without a kernel panic. The tested
kernel contract is commit `d461acfb591c198755f6e84494f8a68a3b6d8bd2`.
Repeated full suite runs remain outstanding.

### Recovery and execution options

Initial nested runs can proceed without external recovery. The runner
enforces a process timeout. This can terminate a stuck launcher but cannot
recover a hung outer host.

External watchdog and recovery design remains separate work. When available,
select a real external control with `--control EXECUTABLE`. The interface is
documented in `~/virtio-villain/docs/suites.md`. It uses `arm`, `recover`
and `disarm` with a run identifier, plus an arm deadline. The watchdog must
survive a hang of the outer Linux host.

```sh
~/virtio-villain/run \
  --suite ~/virtio-villain-mshv \
  --vmm ~/cloud-hypervisor/target/release/cloud-hypervisor \
  --timeout 180 --repeat 3 ML001 MR001 MR003
```

No external control is supplied by this repository. Do not substitute a
script that only kills the launcher or reports success without arming recovery.

The `run-mshv` wrapper invokes this same framework runner with `--suite`
already selected. It is shorthand, not a separate orchestration engine.
The framework loads `lib/suite.py` from this directory. Private helpers live
under `lib`, including the C interface in `lib/mshv.h`. Python policy helpers
use relative imports in an isolated package, not the framework's `villain`
package. The framework supplies `villain` from its `lib/python` directory.
No Python package installation or `PYTHONPATH` setting is required.
For example, from this directory:

```sh
./run-mshv \
  --vmm ~/cloud-hypervisor/target/release/cloud-hypervisor \
  --timeout 180 --repeat 3 ML001 MR001 MR003
```

The neighboring Cloud Hypervisor checkout must be built with its MSHV
backend. The suite boots nested Hyper-V with two vCPUs, 2 GiB RAM and serial
output.

`--initramfs PATH` selects an explicit separate MSHV archive. Omitting test IDs
runs all tests. `--output PATH` selects a new diagnostics directory.
Each test gets a fresh VM boot with its own console log and timeout.
`--jobs N` limits concurrent VMs, with one as the default. For example,
`--jobs 16` runs the seven selected cases concurrently without sharing VMs.
`--repeat 3` runs three complete sequences of those separate boots.
Use `--console` or `-c` for live VM output with complete logs retained.
Console mode runs one VM at a time regardless of `--jobs`. The final summary
is still shown, but individual host result rows and progress updates are
suppressed.
A guest crash or assertion failure is recorded before proceeding to the next
test. Failed external recovery or launcher termination stops further boots.

No native host IOCTL execution is performed by the appliance executable.
Host selftests mock the IOCTL backend. They validate test logic and
cleanup but do not establish kernel conformance or appliance boot success.

## Coverage and results

Each source file contains its test ID, short description and expected
results. The ID consists of a category prefix and a three digit number.
Tests use one registration per source file.

| Prefix | Category | Sources |
| --- | --- | --- |
| ML | MSHV lifecycle | [tests/ml](tests/ml) |
| MR | MSHV register access | [tests/mr](tests/mr) |

Use `./run-mshv --list` to list IDs and descriptions directly from the
source registrations, even before building the executable. Execution uses
the compiled catalog, so rebuild after adding or changing tests.

Exit status 0 means executed tests passed, 1 means assertions/cleanup failed,
and 2 means infrastructure failed. Missing privileges, permissions, device,
boot completion or result records cannot produce a pass. Optional unsupported
features use SKIP. The initial cases require only the stated baseline and do
not silently skip missing prerequisites.

Console logs include each lifecycle cycle and detailed operation/expected/
actual diagnostics. Framework JSON records contain individual verdicts,
overall status, image hashes, launch arguments and recovery errors.

Repeated successful creation establishes only absence of **observable**
resource exhaustion during those cycles. Descriptor closure does not prove
complete hypervisor cleanup. This API exposes no definitive cleanup completion
observation for these tests.

The selected kernel and appliance have booted beneath nested Hyper-V.
Parent partition privileges and actual child partition creation succeeded.
All seven tests passed against the real kernel UAPI in separate boots.
Repeated successful full suite runs remain an unverified acceptance check.
A successful build, host selftest, or ordinary guest boot alone does not
satisfy appliance validation.
