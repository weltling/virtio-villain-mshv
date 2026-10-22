# Private MSHV UAPI suite

This directory is intentionally outside the public Virtio Villain repository.
It contains all MSHV-specific code and policy. Virtio Villain provides the
generic registration, assertions, guest runner, initramfs build and host
orchestration; this is not a separate copy of its framework.

The local repository versions only source, tests, build files and documentation.
Build outputs, generated ABI headers, kernel images and caches under `target`
are not versioned. No remote repository is configured.

The suite currently depends on the new generic interfaces in the local
`~/virtio-villain` working tree. Those public framework changes have not yet
been committed; an unchanged upstream checkout is not sufficient.

## Selected contract

- Full source: `~/linux`.
- Branch inspected: `feature/linux-mshv/6.18`.
- Commit: `d461acfb591c198755f6e84494f8a68a3b6d8bd2`.
- Configuration: `Microsoft/configs/x86/mshv_defconfig` from that source.
- Architecture: x86-64, non-isolated child partitions, VP index 0 initially.

The ABI generator requires this exact commit with no tracked source changes.
It extracts the tested structures and IOCTL definitions from
`include/uapi/linux/mshv.h`, not the headers installed on the host. Register
association layout follows `include/hyperv/hvgdk_mini.h`: 32-byte packed
association, 16-byte value at offset 16, reserved fields zero. General-purpose
register identifiers follow the Hyper-V TLFS x64 register namespace.

`drivers/hv/mshv_root_main.c` establishes:

- Create partition returns an `FD_CLOEXEC` descriptor but does not initialize
  the partition. Call `MSHV_INITIALIZE_PARTITION` before creating the VP.
- Repeated initialization returns zero.
- `MSHV_CREATE_VP` returns a usable `FD_CLOEXEC` descriptor.
- The VP holds a partition reference. Closing the device and partition
  descriptors permits continued VP register access.
- Closing a VP descriptor does not remove the VP from the partition VP array.
  Recreating that index returns `EEXIST`; another index can still be created.
- The retained compatibility register IOCTLs return `EINVAL` for count >128.
  NULL request pointers and NULL arrays with nonzero count return `EFAULT`.
  SET of explicit/intercept suspend registers returns `EINVAL`.

The compatibility IOCTLs are deprecated but remain implemented in this exact
contract; their unexpected absence is a failed assertion, not an optional skip.

Only RAX, RCX, RDX and RBX are written. Their complete 64-bit values are compared,
including all-ones and high-bit values. They have no architectural reserved
bits requiring normalization. The upper 64 bits of the 128-bit ABI value
slot are not asserted for 64-bit registers. Reserved association fields are
zeroed. No mixed valid/invalid batch is used and no rollback/atomicity
guarantee is inferred.

## Execution environment

The kernel executing the IOCTLs must run as a Hyper-V **parent partition**:
root or appropriately provisioned L1VH, non-isolated, with `CreatePartitions`
privilege. The selected kernel checks CPUID `0x40000003`, EBX bit 0 (and excludes
isolated guests) before enabling its parent-partition path. `CPUManagement`
distinguishes a root partition from L1VH; it is not required by this suite.

The appliance checks CPUID, then actually creates, initializes and closes a
partition and VP before running assertions. Device-node presence alone is
insufficient. The host VMM process also needs read/write access to its
`/dev/mshv`; use a fresh login or process with updated group membership.

Required built-in appliance kernel features include `CONFIG_MSHV_ROOT=y`,
`CONFIG_HYPERV=y`, `CONFIG_HYPERV_VMBUS=y`, `CONFIG_BLK_DEV_INITRD=y`,
`CONFIG_RD_GZIP=y`, `CONFIG_DEVTMPFS=y`, `CONFIG_PROC_FS=y`, `CONFIG_SYSFS=y`,
`CONFIG_BINFMT_ELF=y`, and the serial console. The Microsoft configuration
already supplies these; it is not replaced by a minimal custom profile.

### Nested feasibility status

The required model is host VMM -> selected Linux test appliance -> partitions
created by the UAPI tests. Ordinary nested VMX/SVM support is not sufficient.

- Local Cloud Hypervisor `bb5f54912e45f3b9878d0e8e4c8884bd4b4bf21b` implements
  `--cpus nested=on` in its MSHV backend, setting the nested partition-creation
  flag and enabling the nested processor feature.
- Local OpenVMM `54e06dc641735d6019f02135938607b4aa2c0f65` implements nested
  virtualization for WHP/KVM, but its MSHV backend reports it unsupported.
- TMK uses the MSHV backend on the host to run a bare-metal payload; it does not
  supply a Linux kernel UAPI inside the payload and is not a replacement for
  this appliance.

Cloud Hypervisor is a **candidate launcher**, not a validated nested parent
environment. This work has not demonstrated that its Linux guest receives
`CreatePartitions`. An external `--launcher` can supply an appropriately
provisioned Hyper-V environment without changing the suite or framework.
Do not claim nested support until actual child-partition creation succeeds.

## Build

Dependencies on Azure Linux include GCC, glibc-devel, glibc-static, make,
binutils, Python 3, flex, bison, bc, elfutils-libelf-devel, openssl-devel,
zlib-devel and dwarves. Flake8 is required for lint. Rust/Cargo are useful
for rebuilding VMMs but are not needed to compile the C test executable.

```sh
cd ~/mshv-uapi-tests
make mshv-initramfs
make kernel RUSTC=false
make selftest lint
./run-mshv --list
```

`VV_ROOT`/`MSHV_SOURCE` Make variables select alternate framework/source trees.
The wrapper also accepts `VV_ROOT` as an environment variable. All suite and
kernel outputs are beneath `target` in this directory, not the public repo.

The Microsoft configuration records Rust compiler probe versions as zero.
`RUSTC=false` is a make command-line override to match that C-only configuration
even when Rust is installed for VMM development; no kernel configuration
options are silently discarded. The kernel build uses all available CPU cores.

Outputs:

- `target/mshv/init`: static executable, packaged as `/init`.
- `target/mshv/initramfs.cpio.gz`: separate reproducible archive.
- `target/kernel-microsoft/images/vmlinux-x86_64`: Cloud Hypervisor ELF image.
- `target/kernel-microsoft/images/bzImage-x86_64`: compressed Linux image.
- Adjacent config, hashes and generic kernel-builder provenance metadata.

## Run

Arrange real out-of-band watchdog and recovery controls first. The control
interface is documented in `~/virtio-villain/docs/suites.md`: `arm`, `recover`
and `disarm` with a run identifier, plus an arm deadline. The watchdog must
survive a hang of the outer Linux host.

```sh
./run-mshv \
  --kernel target/kernel-microsoft/images/vmlinux-x86_64 \
  --control /path/to/real-external-control \
  --timeout 180 --repeat 3 ML001 MR001 MR003
```

The default candidate launcher is `cloud-hypervisor` with `nested=on`, two
vCPUs, 1 GiB RAM and serial output. Use `--vmm PATH` for another Cloud
Hypervisor build. Use `--launcher EXECUTABLE` for an externally provisioned
parent-partition environment; it receives `--kernel`, `--initramfs`,
`--cmdline` and `--run-id`, must relay the console and remain attached.

`--initramfs PATH` selects an explicit separate MSHV archive. Omitting test IDs
runs all tests. `--output PATH` selects a new diagnostics directory. The thin
`run-mshv` wrapper selects `suite.py` through the public framework entry point
`run --suite`; it does not implement orchestration itself.

No native host IOCTL execution is performed by the appliance executable.
Host-only selftests mock the IOCTL backend. They validate test logic and
cleanup but do not establish kernel conformance or appliance boot success.

## Coverage and results

| ID | Coverage |
| --- | --- |
| ML001 | Create/init/init/VP, descriptor checks, valid register access |
| ML002 | Close both parents, then successfully use VP registers |
| ML003 | Close VP first, exact `EEXIST`, then create/use another VP |
| ML004 | 128 cycles alternating normal and parent-first closure |
| MR001 | Individual RAX values including zero, all ones and high bits |
| MR002 | Distinct four-register batches and replacement values |
| MR003 | Exact `EINVAL`/`EFAULT`, each followed by successful valid operations |

Exit status 0 means executed tests passed, 1 means assertions/cleanup failed,
and 2 means infrastructure failed. Missing privileges, permissions, device,
boot completion or result records cannot produce a pass. Optional unsupported
features use SKIP; the initial cases require only the stated baseline and do
not silently skip missing prerequisites.

Console logs include each lifecycle cycle and detailed operation/expected/
actual diagnostics. Framework JSON records contain individual verdicts,
overall status, image hashes, launch arguments and recovery errors.

Repeated successful creation establishes only absence of **observable**
resource exhaustion during those cycles. Descriptor closure does not prove
complete hypervisor cleanup; this API exposes no definitive cleanup-completion
observation for these tests.

Actual appliance boot and repeated real-kernel IOCTL execution remain required
acceptance checks. A successful build, host selftest, or ordinary guest boot
does not satisfy them.
