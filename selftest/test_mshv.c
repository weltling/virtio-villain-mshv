/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/resource.h>

#include "lib/mshv.h"

static int types[4096], indices[4096], owners[4096], next_fd = 20, open_fds;
static int references, calls, fail_at, corrupt_read, close_failure;
static int opens, fail_open_at, closes, fail_close_at, fd_checks, fail_fd_at;
static int shared_registers, corrupt_release, release_corruptions;
static int break_release, release_breaks;
static struct rlimit mock_limit = {4096, 4096};
static int get_limits, set_limits, fail_get_limit, fail_set_limit_at;
static int partition_rejections, vp_rejections, damage_unwind, retain_failed_vp;
static int unexpected_creation;
static pthread_mutex_t mock_lock = PTHREAD_MUTEX_INITIALIZER;
static int fd_flags = FD_CLOEXEC;
static struct mock_partition {
    int references;
    int initialized;
    int broken;
    int vp_created[2];
    uint64_t values[2][4];
} partitions[2];
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

static int allocate(int type, int index, int owner)
{
    assert(next_fd < 4096);
    int fd = next_fd++;
    types[fd] = type;
    indices[fd] = index;
    owners[fd] = owner;
    ++open_fds;
    return fd;
}

static int mock_open(const char *path, int flags)
{
    assert(!strcmp(path, "/dev/mshv"));
    assert(flags == (O_RDWR | O_CLOEXEC));
    if (++opens == fail_open_at) {
        errno = EACCES;
        return -1;
    }
    if (mock_limit.rlim_cur == 0) {
        errno = EMFILE;
        return -1;
    }
    return allocate(1, 0, -1);
}

static int mock_fcntl(int fd, int command)
{
    assert(types[fd] && command == F_GETFD);
    if (++fd_checks == fail_fd_at) {
        errno = EBADF;
        return -1;
    }
    if (fd_flags < 0)
        errno = EBADF;
    return fd_flags;
}

static int mock_close(int fd)
{
    assert(types[fd]);
    if (types[fd] != 1) {
        struct mock_partition *partition = &partitions[owners[fd]];
        assert(references > 0 && partition->references > 0);
        --references;
        if (--partition->references == 0) {
            memset(partition, 0, sizeof(*partition));
            for (unsigned i = 0; break_release &&
                 i < sizeof(partitions) / sizeof(partitions[0]); ++i) {
                if (partitions[i].references) {
                    partitions[i].broken = 1;
                    ++release_breaks;
                }
            }
            if (corrupt_release) {
                for (unsigned i = 0; i < sizeof(partitions) / sizeof(partitions[0]); ++i) {
                    if (partitions[i].references) {
                        partitions[i].values[0][0] ^= 1;
                        ++release_corruptions;
                    }
                }
            }
        }
    }
    types[fd] = 0;
    --open_fds;
    ++closes;
    if (close_failure || closes == fail_close_at) {
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

static int is_device_request(unsigned long req)
{
    return req == MSHV_CREATE_PARTITION || req == MSHV_ROOT_HVCALL;
}

static int is_vp_request(unsigned long req)
{
    switch (req) {
    case MSHV_RUN_VP:
    case MSHV_GET_VP_STATE:
    case MSHV_SET_VP_STATE:
    case MSHV_TRANSLATE_GVA:
    case MSHV_GET_VP_REGISTERS:
    case MSHV_SET_VP_REGISTERS:
    case MSHV_VP_REGISTER_INTERCEPT_RESULT:
    case MSHV_GET_VP_CPUID_VALUES:
    case MSHV_READ_GPA:
    case MSHV_WRITE_GPA:
    case MSHV_ROOT_HVCALL:
        return 1;
    default:
        return 0;
    }
}

static int is_snp_partition_request(unsigned long req)
{
    switch (req) {
    case MSHV_MODIFY_GPA_HOST_ACCESS:
    case MSHV_IMPORT_ISOLATED_PAGES:
    case MSHV_COMPLETE_ISOLATED_IMPORT:
    case MSHV_ISSUE_PSP_GUEST_REQUEST:
    case MSHV_SEV_SNP_AP_CREATE:
        return 1;
    default:
        return 0;
    }
}

static int is_partition_request(unsigned long req)
{
    if (is_snp_partition_request(req))
        return 1;
    switch (req) {
    case MSHV_INITIALIZE_PARTITION:
    case MSHV_CREATE_VP:
    case MSHV_SET_GUEST_MEMORY:
    case MSHV_IRQFD:
    case MSHV_IOEVENTFD:
    case MSHV_SET_MSI_ROUTING:
    case MSHV_GET_GPAP_ACCESS_BITMAP:
    case MSHV_CREATE_DEVICE:
    case MSHV_GET_GPAP_RANGE_ACCESS:
    case MSHV_SCRUB_PARTITION:
    case MSHV_INSTALL_INTERCEPT:
    case MSHV_ASSERT_INTERRUPT:
    case MSHV_SET_PARTITION_PROPERTY:
    case MSHV_GET_PARTITION_PROPERTY:
    case MSHV_SIGNAL_EVENT_DIRECT:
    case MSHV_POST_MESSAGE_DIRECT:
    case MSHV_REGISTER_DELIVERABILITY_NOTIFICATIONS:
    case MSHV_ROOT_HVCALL:
        return 1;
    default:
        return 0;
    }
}

static int mock_ioctl(int fd, unsigned long request, void *arg)
{
    if (fd < 0 || fd >= (int)(sizeof(types) / sizeof(types[0])) || !types[fd])
        return reject(EBADF);
    if (++calls == fail_at)
        return reject(EIO);
    if (types[fd] != 1 && partitions[owners[fd]].broken)
        return reject(EIO);

    if (types[fd] == 1) {
        if (!is_device_request(request))
            return reject(ENOTTY);
        if (request == MSHV_CREATE_PARTITION) {
            struct mshv_create_partition *args = arg;
            if (!args)
                return reject(EFAULT);
            if ((args->pt_flags & ~MSHV_PT_FLAGS_MASK) ||
                args->pt_isolation >= MSHV_PT_ISOLATION_COUNT)
                return reject(EINVAL);
            if (mock_limit.rlim_cur == 0 && unexpected_creation != 1) {
                ++partition_rejections;
                if (damage_unwind == 1)
                    partitions[0].values[0][0] ^= 1;
                return reject(EMFILE);
            }
            unsigned owner = 0;
            while (owner < sizeof(partitions) / sizeof(partitions[0]) &&
                   partitions[owner].references)
                ++owner;
            assert(owner < sizeof(partitions) / sizeof(partitions[0]));
            partitions[owner].references = 1;
            partitions[owner].initialized = 0;
            ++references;
            return allocate(2, 0, owner);
        }
        if (request == MSHV_ROOT_HVCALL) {
            if (!arg)
                return reject(EFAULT);
            return 0;
        }
        return reject(ENOTTY);
    }

    if (types[fd] == 2) {
        if (!is_partition_request(request))
            return reject(ENOTTY);
        if (is_snp_partition_request(request))
            return reject(EOPNOTSUPP);
        if (request == MSHV_INITIALIZE_PARTITION) {
            partitions[owners[fd]].initialized = 1;
            return 0;
        }
        if (request == MSHV_CREATE_VP) {
            struct mshv_create_vp *args = arg;
            if (!args)
                return reject(EFAULT);
            if (!partitions[owners[fd]].initialized)
                return reject(EIO);
            if (args->vp_index >= 256)
                return reject(EINVAL);
            struct mock_partition *partition = &partitions[owners[fd]];
            assert(args->vp_index < 2);
            if (partition->vp_created[args->vp_index])
                return reject(EEXIST);
            if (mock_limit.rlim_cur == 0 && unexpected_creation != 2) {
                ++vp_rejections;
                if (damage_unwind == 2)
                    partitions[0].values[0][0] ^= 1;
                if (retain_failed_vp)
                    partition->vp_created[args->vp_index] = 1;
                return reject(EMFILE);
            }
            partition->vp_created[args->vp_index] = 1;
            ++partition->references;
            ++references;
            return allocate(3, args->vp_index, owners[fd]);
        }
        if (request == MSHV_SET_GUEST_MEMORY) {
            if (!arg)
                return reject(EFAULT);
            struct mshv_user_mem_region *m = arg;
            if (!m->size || (m->size % 4096) || (m->userspace_addr % 4096) || (m->flags & ~0x07))
                return reject(EINVAL);
            return 0;
        }
        if (request == MSHV_IRQFD) {
            if (!arg)
                return reject(EFAULT);
            struct mshv_user_irqfd *irq = arg;
            if (irq->flags & ~0x03)
                return reject(EINVAL);
            if (irq->fd < 0)
                return reject(EBADF);
            return 0;
        }
        if (request == MSHV_IOEVENTFD) {
            if (!arg)
                return reject(EFAULT);
            struct mshv_user_ioeventfd *io = arg;
            if (io->flags & ~0x07)
                return reject(EINVAL);
            if (io->len != 1 && io->len != 2 && io->len != 4 && io->len != 8)
                return reject(EINVAL);
            return 0;
        }
        if (!arg && request != MSHV_SCRUB_PARTITION)
            return reject(EFAULT);
        return 0;
    }

    assert(types[fd] == 3);
    if (!is_vp_request(request))
        return reject(ENOTTY);
    if (request == MSHV_GET_VP_STATE || request == MSHV_SET_VP_STATE) {
        if (!arg)
            return reject(EFAULT);
        struct mshv_get_set_vp_state *s = arg;
        if (s->type >= 5 || !s->buf_sz || (s->buf_sz % 4096) || (s->buf_ptr % 4096))
            return reject(EINVAL);
        return 0;
    }
    if (request == MSHV_GET_VP_CPUID_VALUES) {
        if (!arg)
            return reject(EFAULT);
        return 0;
    }
    if (request == MSHV_GET_VP_REGISTERS || request == MSHV_SET_VP_REGISTERS) {
        struct mshv_vp_registers *args = arg;
        if (!args)
            return reject(EFAULT);
        if (args->count > MSHV_VP_MAX_REGISTERS)
            return reject(EINVAL);
        if (!args->regs)
            return reject(EFAULT);
        struct mock_partition *partition = &partitions[shared_registers ? 0 : owners[fd]];
        for (unsigned i = 0; i < args->count; ++i) {
            struct hv_register_assoc *reg = &args->regs[i];
            if (request == MSHV_SET_VP_REGISTERS &&
                (reg->name == VV_EXPLICIT_SUSPEND || reg->name == VV_INTERCEPT_SUSPEND))
                return reject(EINVAL);
            assert(reg->name >= VV_RAX && reg->name <= VV_RBX);
            unsigned n = reg->name - VV_RAX;
            if (request == MSHV_SET_VP_REGISTERS)
                partition->values[indices[fd]][n] = reg->value.reg64;
            else
                reg->value.reg64 = partition->values[indices[fd]][n] ^ corrupt_read;
        }
        return 0;
    }
    if (!arg && request != MSHV_RUN_VP)
        return reject(EFAULT);
    return 0;
}

int __wrap_open(const char *path, int flags, ...)
{
    pthread_mutex_lock(&mock_lock);
    int rc = mock_open(path, flags);
    pthread_mutex_unlock(&mock_lock);
    return rc;
}

int __wrap_fcntl(int fd, int command, ...)
{
    pthread_mutex_lock(&mock_lock);
    int rc = mock_fcntl(fd, command);
    pthread_mutex_unlock(&mock_lock);
    return rc;
}

int __wrap_close(int fd)
{
    pthread_mutex_lock(&mock_lock);
    int rc = mock_close(fd);
    pthread_mutex_unlock(&mock_lock);
    return rc;
}

int __wrap_ioctl(int fd, unsigned long request, ...)
{
    va_list ap;
    va_start(ap, request);
    void *arg = va_arg(ap, void *);
    va_end(ap);
    pthread_mutex_lock(&mock_lock);
    int rc = mock_ioctl(fd, request, arg);
    pthread_mutex_unlock(&mock_lock);
    return rc;
}

int __wrap_getrlimit(int resource, struct rlimit *limit)
{
    assert(resource == RLIMIT_NOFILE);
    ++get_limits;
    if (fail_get_limit)
        return reject(EIO);
    *limit = mock_limit;
    return 0;
}

int __wrap_setrlimit(int resource, const struct rlimit *limit)
{
    assert(resource == RLIMIT_NOFILE);
    assert((limit->rlim_cur == 0 || limit->rlim_cur == 4096) && limit->rlim_max == 4096);
    if (++set_limits == fail_set_limit_at)
        return reject(EIO);
    mock_limit = *limit;
    return 0;
}

static test_result_t execute(const struct vv_test_entry *test)
{
    struct mshv_fixture f;
    assert(open_fds == 0 && references == 0);
    next_fd = 20;
    calls = opens = closes = fd_checks = 0;
    get_limits = set_limits = partition_rejections = vp_rejections = 0;
    mshv_init_context(&f);
    test_result_t result = test->fn(&f);
    if (mshv_cleanup_context(&f) != TEST_PASS)
        result = TEST_FAIL;
    assert(open_fds == 0 && references == 0);
    assert(mock_limit.rlim_cur == 4096 && mock_limit.rlim_max == 4096);
    for (unsigned i = 0; i < sizeof(partitions) / sizeof(partitions[0]); ++i)
        assert(partitions[i].references == 0);
    return result;
}

static void check_ioctl_table(void)
{
    assert(mshv_ioctl_count == 34);
    unsigned routing_checks = 0, pointer_checks = 0;
    for (size_t i = 0; i < mshv_ioctl_count; ++i) {
        const struct mshv_ioctl_entry *entry = &mshv_ioctl_table[i];
        unsigned targets = 0;
        if (is_device_request(entry->request))
            targets |= VV_IOCTL_DEVICE;
        if (is_partition_request(entry->request))
            targets |= VV_IOCTL_PARTITION;
        if (is_vp_request(entry->request))
            targets |= VV_IOCTL_VP;
        assert(targets && entry->targets == targets);
        assert(_IOC_TYPE(entry->request) == MSHV_IOCTL);
        assert(!strncmp(entry->name, "MSHV_", 5));
        for (size_t j = 0; j < i; ++j) {
            assert(entry->request != mshv_ioctl_table[j].request);
            assert(strcmp(entry->name, mshv_ioctl_table[j].name));
        }
        int expected = EFAULT;
        if (is_snp_partition_request(entry->request))
            expected = EOPNOTSUPP;
        if (entry->request == MSHV_INITIALIZE_PARTITION ||
            entry->request == MSHV_SCRUB_PARTITION || entry->request == MSHV_RUN_VP)
            expected = 0;
        assert(entry->null_errno == expected);
        const unsigned all_targets[] = {VV_IOCTL_DEVICE, VV_IOCTL_PARTITION, VV_IOCTL_VP};
        for (size_t j = 0; j < sizeof(all_targets) / sizeof(all_targets[0]); ++j) {
            if (!(targets & all_targets[j]))
                ++routing_checks;
            else if (entry->null_errno)
                ++pointer_checks;
        }
    }
    assert(routing_checks == 66 && pointer_checks == 33);
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
    check_ioctl_table();
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
    int fd = allocate(1, 0, -1);
    fd_flags = 0;
    assert(mshv_check_fd(fd, "MSHV_CREATE_VP index=%u", vp.vp_index) == TEST_FAIL);
    fd_flags = -1;
    assert(mshv_check_fd(fd, "MSHV_CREATE_VP index=%u", vp.vp_index) == TEST_FAIL);
    fd_flags = FD_CLOEXEC;
    assert(mshv_check_fd(fd, "MSHV_CREATE_VP index=%u", vp.vp_index) == TEST_PASS);
    assert(__wrap_close(fd) == 0);
    check_preflight();

    const struct vv_test_entry *lifecycle = NULL, *single = NULL, *negative = NULL;
    const struct vv_test_entry *isolation = NULL, *concurrent = NULL, *unwind = NULL;
    int isolation_calls = 0, isolation_opens = 0, isolation_closes = 0, isolation_fds = 0;
    int concurrent_opens = 0, concurrent_closes = 0, concurrent_fds = 0;
    int unwind_calls = 0, unwind_opens = 0, unwind_closes = 0, unwind_fds = 0;
    int unwind_limits = 0;
    for (const struct vv_test_entry *test = __start_mshv_registry;
         test < __stop_mshv_registry; ++test) {
        assert(execute(test) == TEST_PASS);
        if (!strcmp(test->name, "ML0001"))
            lifecycle = test;
        if (!strcmp(test->name, "MR0001"))
            single = test;
        if (!strcmp(test->name, "MR0003"))
            negative = test;
        if (!strcmp(test->name, "ML0008"))
            assert(calls == 3 + 66 + 2);
        if (!strcmp(test->name, "ML0010"))
            assert(calls == 3 + 33 + 2);
        if (!strcmp(test->name, "ML0005")) {
            isolation = test;
            isolation_calls = calls;
            isolation_opens = opens;
            isolation_closes = closes;
            isolation_fds = fd_checks;
        }
        if (!strcmp(test->name, "ML0006")) {
            concurrent = test;
            concurrent_opens = opens;
            concurrent_closes = closes;
            concurrent_fds = fd_checks;
        }
        if (!strcmp(test->name, "ML0007")) {
            unwind = test;
            unwind_calls = calls;
            unwind_opens = opens;
            unwind_closes = closes;
            unwind_fds = fd_checks;
            unwind_limits = set_limits;
            assert(get_limits == 1 && set_limits == 2049);
            assert(partition_rejections == 512 && vp_rejections == 512);
        }
    }
    assert(lifecycle && single && negative && isolation && concurrent && unwind);
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
    for (int step = 1; step <= isolation_calls; ++step) {
        fail_at = step;
        assert(execute(isolation) == TEST_FAIL);
    }
    fail_at = 0;
    for (int step = 1; step <= isolation_opens; ++step) {
        fail_open_at = step;
        assert(execute(isolation) == TEST_FAIL);
    }
    fail_open_at = 0;
    for (int step = 1; step <= isolation_fds; ++step) {
        fail_fd_at = step;
        assert(execute(isolation) == TEST_FAIL);
    }
    fail_fd_at = 0;
    for (int step = 1; step <= isolation_closes; ++step) {
        fail_close_at = step;
        assert(execute(isolation) == TEST_FAIL);
    }
    fail_close_at = 0;
    shared_registers = 1;
    assert(execute(isolation) == TEST_FAIL);
    shared_registers = 0;
    corrupt_release = 1;
    assert(execute(isolation) == TEST_FAIL);
    assert(release_corruptions == 1);
    corrupt_release = 0;
    assert(execute(isolation) == TEST_PASS);
    puts("mshv isolation mock checks passed");
    assert(concurrent_opens == 65 && concurrent_fds == 195 && concurrent_closes == 195);
    for (int step = 1; step <= 256; ++step) {
        fail_at = step;
        assert(execute(concurrent) == TEST_FAIL);
    }
    fail_at = 0;
    for (int step = 1; step <= concurrent_opens; ++step) {
        fail_open_at = step;
        assert(execute(concurrent) == TEST_FAIL);
    }
    fail_open_at = 0;
    for (int step = 1; step <= concurrent_fds; ++step) {
        fail_fd_at = step;
        assert(execute(concurrent) == TEST_FAIL);
    }
    fail_fd_at = 0;
    for (int step = 1; step <= concurrent_closes; ++step) {
        fail_close_at = step;
        assert(execute(concurrent) == TEST_FAIL);
    }
    fail_close_at = 0;
    break_release = 1;
    assert(execute(concurrent) == TEST_FAIL);
    assert(release_breaks >= 1);
    break_release = 0;
    corrupt_read = 1;
    assert(execute(concurrent) == TEST_FAIL);
    corrupt_read = 0;
    assert(execute(concurrent) == TEST_PASS);
    puts("mshv concurrency mock checks passed");
    /* Cover both failure bursts, successful retries and the final cycle. */
    for (int step = 1; step <= 64; ++step) {
        fail_at = step;
        assert(execute(unwind) == TEST_FAIL);
    }
    fail_at = unwind_calls;
    assert(execute(unwind) == TEST_FAIL);
    fail_at = 0;
    for (int step = 1; step <= unwind_opens; ++step) {
        fail_open_at = step;
        assert(execute(unwind) == TEST_FAIL);
    }
    fail_open_at = 0;
    for (int step = 1; step <= unwind_fds; ++step) {
        fail_fd_at = step;
        assert(execute(unwind) == TEST_FAIL);
    }
    fail_fd_at = 0;
    for (int step = 1; step <= unwind_closes; ++step) {
        fail_close_at = step;
        assert(execute(unwind) == TEST_FAIL);
    }
    fail_close_at = 0;
    fail_get_limit = 1;
    assert(execute(unwind) == TEST_FAIL);
    fail_get_limit = 0;
    for (int step = 1; step <= 32; ++step) {
        fail_set_limit_at = step;
        assert(execute(unwind) == TEST_FAIL);
    }
    for (int step = unwind_limits - 2; step <= unwind_limits; ++step) {
        fail_set_limit_at = step;
        assert(execute(unwind) == TEST_FAIL);
    }
    fail_set_limit_at = 0;
    for (int mode = 1; mode <= 2; ++mode) {
        damage_unwind = mode;
        assert(execute(unwind) == TEST_FAIL);
    }
    damage_unwind = 0;
    retain_failed_vp = 1;
    assert(execute(unwind) == TEST_FAIL);
    retain_failed_vp = 0;
    for (int mode = 1; mode <= 2; ++mode) {
        unexpected_creation = mode;
        assert(execute(unwind) == TEST_FAIL);
    }
    unexpected_creation = 0;
    assert(execute(unwind) == TEST_PASS);
    puts("mshv unwind mock checks passed");
    struct mshv_fixture f = {.device = -1, .partition = -1, .vp = -1};
    assert(mshv_roundtrip(&f, 0, 0) == TEST_FAIL);
    assert(mshv_roundtrip(&f, 5, 0) == TEST_FAIL);
    assert(mshv_check_gprs(&f, 0, 0) == TEST_FAIL);
    assert(mshv_check_gprs(&f, 5, 0) == TEST_FAIL);
    puts("mshv mock checks passed");
    return 0;
}
