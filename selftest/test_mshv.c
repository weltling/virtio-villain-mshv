/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "lib/mshv.h"

static int types[4096], indices[4096], next_fd = 20, open_fds;
static int vp_created[2], references, calls, fail_at, corrupt_read, close_failure;
static int fd_flags = FD_CLOEXEC;
static uint64_t values[2][4];
static unsigned cpuid_ecx = HYPERV_HYPERVISOR_PRESENT_BIT;
static unsigned cpuid_max = HYPERV_CPUID_FEATURES;
static unsigned cpuid_interface = VV_HYPERV_INTERFACE_HV1_SIGNATURE;
static unsigned cpuid_privileges = HV_CREATE_PARTITIONS;

void mshv_test_cpuid(unsigned leaf, unsigned *eax, unsigned *ebx,
                     unsigned *ecx, unsigned *edx)
{
    *eax = *ebx = *ecx = *edx = 0;
    switch (leaf) {
    case VV_X86_CPUID_FEATURES:
        *ecx = cpuid_ecx;
        break;
    case HYPERV_CPUID_VENDOR_AND_MAX_FUNCTIONS:
        *eax = cpuid_max;
        break;
    case HYPERV_CPUID_INTERFACE:
        *eax = cpuid_interface;
        break;
    case HYPERV_CPUID_FEATURES:
        *ebx = cpuid_privileges;
        break;
    default:
        assert(0);
    }
}

static int allocate(int type, int index)
{
    assert(next_fd < 4096);
    int fd = next_fd++;
    types[fd] = type;
    indices[fd] = index;
    ++open_fds;
    return fd;
}

int __wrap_open(const char *path, int flags, ...)
{
    assert(!strcmp(path, "/dev/mshv"));
    assert(flags == (O_RDWR | O_CLOEXEC));
    return allocate(1, 0);
}

int __wrap_fcntl(int fd, int command, ...)
{
    assert(types[fd] && command == F_GETFD);
    if (fd_flags < 0)
        errno = EBADF;
    return fd_flags;
}

int __wrap_close(int fd)
{
    assert(types[fd]);
    if (types[fd] != 1 && --references == 0) {
        memset(vp_created, 0, sizeof(vp_created));
        memset(values, 0, sizeof(values));
    }
    types[fd] = 0;
    --open_fds;
    if (close_failure) {
        close_failure = 0;
        errno = EINTR;
        return -1;
    }
    return 0;
}

static int reject(int error)
{
    errno = error;
    return -1;
}

int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    assert(types[fd]);
    if (++calls == fail_at)
        return reject(EIO);
    if (types[fd] == 1 && request == MSHV_CREATE_PARTITION) {
        struct mshv_create_partition *args = arg;
        assert(args && args->pt_flags == VV_MSHV_PARTITION_FLAGS_NONE &&
               args->pt_isolation == MSHV_PT_ISOLATION_NONE);
        assert(references == 0);
        ++references;
        return allocate(2, 0);
    }
    if (types[fd] == 2 && request == MSHV_INITIALIZE_PARTITION)
        return 0;
    if (types[fd] == 2 && request == MSHV_CREATE_VP) {
        struct mshv_create_vp *args = arg;
        assert(args && args->vp_index < 2);
        if (vp_created[args->vp_index])
            return reject(EEXIST);
        vp_created[args->vp_index] = 1;
        ++references;
        return allocate(3, args->vp_index);
    }
    assert(types[fd] == 3);
    assert(request == MSHV_GET_VP_REGISTERS || request == MSHV_SET_VP_REGISTERS);
    struct mshv_vp_registers *args = arg;
    if (!args)
        return reject(EFAULT);
    if (args->count > MSHV_VP_MAX_REGISTERS)
        return reject(EINVAL);
    if (!args->regs)
        return reject(EFAULT);
    for (unsigned i = 0; i < args->count; ++i) {
        struct hv_register_assoc *reg = &args->regs[i];
        if (request == MSHV_SET_VP_REGISTERS &&
            (reg->name == VV_EXPLICIT_SUSPEND || reg->name == VV_INTERCEPT_SUSPEND))
            return reject(EINVAL);
        assert(reg->name >= VV_RAX && reg->name <= VV_RBX);
        unsigned n = reg->name - VV_RAX;
        if (request == MSHV_SET_VP_REGISTERS)
            values[indices[fd]][n] = reg->value.reg64;
        else
            reg->value.reg64 = values[indices[fd]][n] ^ corrupt_read;
    }
    return 0;
}

static test_result_t execute(const struct vv_test_entry *test)
{
    struct mshv_fixture f;
    mshv_init_context(&f);
    test_result_t result = test->fn(&f);
    if (mshv_cleanup_context(&f) != TEST_PASS)
        result = TEST_FAIL;
    assert(open_fds == 0 && references == 0);
    return result;
}

static void check_preflight(void)
{
    int previous_calls = calls;
    cpuid_ecx = 0;
    assert(mshv_preflight() == -1);
    cpuid_ecx = HYPERV_HYPERVISOR_PRESENT_BIT;
    cpuid_max = HYPERV_CPUID_INTERFACE;
    assert(mshv_preflight() == -1);
    cpuid_max = HYPERV_CPUID_FEATURES;
    cpuid_interface = 0;
    assert(mshv_preflight() == -1);
    cpuid_interface = VV_HYPERV_INTERFACE_HV1_SIGNATURE;
    cpuid_privileges = 0;
    assert(mshv_preflight() == -1);
    cpuid_privileges = HV_CREATE_PARTITIONS | HV_ISOLATION;
    assert(mshv_preflight() == -1);
    assert(calls == previous_calls && open_fds == 0 && references == 0);
    cpuid_privileges = HV_CREATE_PARTITIONS;
    assert(mshv_preflight() == 0);
    assert(open_fds == 0 && references == 0);
    for (int step = 1; step <= 3; ++step) {
        calls = 0;
        fail_at = step;
        assert(mshv_preflight() == -1);
        assert(open_fds == 0 && references == 0);
    }
    fail_at = 0;
    close_failure = 1;
    assert(mshv_preflight() == -1);
    assert(open_fds == 0 && references == 0);
    assert(mshv_preflight() == 0);
    assert(open_fds == 0 && references == 0);
}

int main(void)
{
    uint32_t signature = VV_HYPERV_INTERFACE_HV1_SIGNATURE;
    assert(!memcmp(&signature, "Hv#1", sizeof(signature)));
    assert(HYPERV_HYPERVISOR_PRESENT_BIT == UINT32_C(0x80000000));
    assert(HV_CREATE_PARTITIONS == UINT32_C(0x00000001));
    assert(HV_ISOLATION == UINT32_C(0x00400000));
    struct mshv_create_partition partition = {
        .pt_flags = 0xabc,
        .pt_isolation = UINT64_C(0x123456789abcdef0),
    };
    struct mshv_create_vp vp = {.vp_index = 7};
    errno = EACCES;
    assert(mshv_check_fd(-1,
                        "MSHV_CREATE_PARTITION flags=0x%" PRIx64 " isolation=0x%" PRIx64,
                        (uint64_t)partition.pt_flags,
                        (uint64_t)partition.pt_isolation) == TEST_FAIL);
    int fd = allocate(1, 0);
    fd_flags = 0;
    assert(mshv_check_fd(fd, "MSHV_CREATE_VP index=%u", vp.vp_index) == TEST_FAIL);
    fd_flags = -1;
    assert(mshv_check_fd(fd, "MSHV_CREATE_VP index=%u", vp.vp_index) == TEST_FAIL);
    fd_flags = FD_CLOEXEC;
    assert(mshv_check_fd(fd, "MSHV_CREATE_VP index=%u", vp.vp_index) == TEST_PASS);
    assert(__wrap_close(fd) == 0);
    check_preflight();

    const struct vv_test_entry *lifecycle = NULL, *single = NULL, *negative = NULL;
    unsigned count = 0;
    for (const struct vv_test_entry *test = __start_mshv_registry;
         test < __stop_mshv_registry; ++test) {
        assert(execute(test) == TEST_PASS);
        if (!strcmp(test->name, "ML001"))
            lifecycle = test;
        if (!strcmp(test->name, "MR001"))
            single = test;
        if (!strcmp(test->name, "MR003"))
            negative = test;
        ++count;
    }
    assert(count == 7 && lifecycle && single && negative);
    for (int step = 1; step <= 6; ++step) {
        calls = 0;
        fail_at = step;
        assert(execute(lifecycle) == TEST_FAIL);
    }
    fail_at = 0;
    corrupt_read = 1;
    assert(execute(single) == TEST_FAIL);
    corrupt_read = 0;
    close_failure = 1;
    assert(execute(lifecycle) == TEST_FAIL);
    const int negative_failures[] = {4, 10, 13, 19};
    for (unsigned i = 0; i < sizeof(negative_failures) / sizeof(negative_failures[0]); ++i) {
        calls = 0;
        fail_at = negative_failures[i];
        assert(execute(negative) == TEST_FAIL);
    }
    fail_at = 0;
    assert(execute(negative) == TEST_PASS);
    struct mshv_fixture f = {.device = -1, .partition = -1, .vp = -1};
    assert(mshv_roundtrip(&f, 0, 0) == TEST_FAIL);
    assert(mshv_roundtrip(&f, 5, 0) == TEST_FAIL);
    puts("mshv mock checks passed");
    return 0;
}
