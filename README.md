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

Thus `nested=on` on this launcher is not enough to run these UAPI tests.
Do not bypass the privilege check or change the expected test results.
An external `--launcher` can supply an appropriately
provisioned Hyper-V environment without changing the suite or framework.
The nested Hyper-V boot image described below supplies that environment.
Actual child partition creation and all seven UAPI tests passed with it.

## Build

Dependencies on Azure Linux include GCC, glibc-devel, glibc-static, make,
binutils, Python 3, flex, bison, bc, elfutils-libelf-devel, openssl-devel,
zlib-devel and dwarves. Flake8 is required for lint. Rust/Cargo are useful
for rebuilding VMMs but are not needed to compile the C test executable.

```sh
cd ~/virtio-villain-mshv
make mshv-initramfs
make kernel RUSTC=false
make selftest lint
./run-mshv --list
```

`VV_ROOT`/`MSHV_SOURCE` Make variables select alternate framework/source trees.
The wrapper also accepts `VV_ROOT` as an environment variable. All suite and
kernel outputs are beneath `target` in this directory, not the public repo.

The Microsoft configuration records Rust compiler probe versions as zero.
`RUSTC=false` is a make command line override to match that C configuration
even when Rust is installed for VMM development. No kernel configuration
options are silently discarded. The kernel build uses all available CPU cores.

Outputs:

- `target/mshv/init`: static executable, packaged as `/init`.
- `target/mshv/initramfs.cpio.gz`: separate reproducible archive.
- `target/kernel-microsoft/images/vmlinux-x86_64`: Cloud Hypervisor ELF image.
- `target/kernel-microsoft/images/bzImage-x86_64`: compressed Linux image.
- Adjacent config, hashes and generic kernel builder provenance metadata.

## Run

### Nested Hyper-V boot image

The direct Linux boot below does not grant parent privileges. To start a
second Hyper-V instance before Linux, construct a separate UEFI boot disk
from the installed components:

```sh
python3 mshv/boot_image.py --output target/nested-hyperv/appliance
```

The builder reads the host ESP and copies the installed shim, GRUB and
Hyper-V loaders. It also copies both CPU vendor hypervisor binaries and
`kdstub.dll`. All inputs must be readable by the current user. The builder
never elevates privileges. Use `--esp PATH` to select a readable copy of
the ESP components, or set `MSHV_ESP` for both the builder and launcher.
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
  --suite ~/virtio-villain-mshv/suite.py \
  --launcher ~/virtio-villain-mshv/launch-nested \
  --kernel ~/virtio-villain-mshv/target/kernel-microsoft/images/bzImage-x86_64 \
  --timeout 120 --jobs 16
```

`launch-nested` assembles a new disk for each test run. It uses the neighboring
Cloud Hypervisor build with `nested=on`. Set `MSHV_VMM` to an absolute path to
select another Cloud Hypervisor binary. This boot path requires `bzImage`,
not the ELF `vmlinux` image used for direct Linux boot.

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

### Direct Linux boot

Initial nested runs can proceed without external recovery. The runner
enforces a process timeout. This can terminate a stuck launcher but cannot
recover a hung outer host.

External watchdog and recovery design remains separate work. When available,
select a real external control with `--control EXECUTABLE`. The interface is
documented in `~/virtio-villain/docs/suites.md`. It uses `arm`, `recover`
and `disarm` with a run identifier, plus an arm deadline. The watchdog must
survive a hang of the outer Linux host.

```sh
sudo setcap cap_net_admin=ep \
  ~/cloud-hypervisor/target/release/cloud-hypervisor

~/virtio-villain/run \
  --suite ~/virtio-villain-mshv/suite.py \
  --vmm ~/cloud-hypervisor/target/release/cloud-hypervisor \
  --kernel ~/virtio-villain-mshv/target/kernel-microsoft/images/vmlinux-x86_64 \
  --timeout 180 --repeat 3 ML001 MR001 MR003
```

No external control is supplied by this repository. Do not substitute a
script that only kills the launcher or reports success without arming recovery.

The `run-mshv` wrapper invokes this same framework runner with `--suite`
already selected. It is shorthand, not a separate orchestration engine.
For example, from this directory:

```sh
./run-mshv \
  --vmm ~/cloud-hypervisor/target/release/cloud-hypervisor \
  --kernel target/kernel-microsoft/images/vmlinux-x86_64 \
  --timeout 180 --repeat 3 ML001 MR001 MR003
```

The neighboring Cloud Hypervisor checkout must be built with its MSHV
backend. Reapply `setcap` after rebuilding if the binary was replaced.
The TAP capability supports the virtio test runner and is not evidence of
Hyper-V child partition privileges.

The default candidate launcher is `cloud-hypervisor` with `nested=on`, two
vCPUs, 1 GiB RAM and serial output. Use `--vmm PATH` for another Cloud
Hypervisor build. Use `--launcher EXECUTABLE` for an externally provisioned
parent partition environment. It receives `--kernel`, `--initramfs`,
`--cmdline` and `--run-id`. It must relay the console and remain attached.

`--initramfs PATH` selects an explicit separate MSHV archive. Omitting test IDs
runs all tests. `--output PATH` selects a new diagnostics directory.
Each test gets a fresh VM boot with its own console log and timeout.
`--jobs N` limits concurrent VMs, with one as the default. For example,
`--jobs 16` runs the seven selected cases concurrently without sharing VMs.
`--repeat 3` runs three complete sequences of those separate boots.
A guest crash or assertion failure is recorded before proceeding to the next
test. Failed external recovery or launcher termination stops further boots.

No native host IOCTL execution is performed by the appliance executable.
Host selftests mock the IOCTL backend. They validate test logic and
cleanup but do not establish kernel conformance or appliance boot success.

## Coverage and results

Test cases live in `tests/mshv`, with one registered case per source file.

| ID | Coverage |
| --- | --- |
| ML001 | Create/init/init/VP, descriptor checks, valid register access |
| ML002 | Close both parents, then successfully use VP registers |
| ML003 | Close VP first, exact `EEXIST`, then create/use another VP |
| ML004 | 128 cycles alternating normal closure and closing parents first |
| MR001 | Individual RAX values including zero, all ones and high bits |
| MR002 | Distinct batches of four registers and replacement values |
| MR003 | Exact `EINVAL`/`EFAULT`, each followed by successful valid operations |

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
