/* SPDX-License-Identifier: Apache-2.0 */
/*
 * Shared partition and virtual processor lifecycle checks.
 * Create with zero flags/isolation, initialize, then create virtual processor
 * (VP) zero. Each file descriptor (FD) must be valid and have FD_CLOEXEC.
 * Fixture cleanup closes owned FDs after returned successes and failures.
 * A closed FD is marked unowned to avoid closing it twice. Descriptor closure
 * is not evidence of complete hypervisor resource reclamation.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include <string.h>
#include <unistd.h>

#include "lib/mshv.h"

#define IOCTL_ENTRY(request, targets, error) {request, #request, targets, error}

const struct mshv_ioctl_entry mshv_ioctl_table[] = {
    IOCTL_ENTRY(MSHV_CREATE_PARTITION, VV_IOCTL_DEVICE, EFAULT),
    IOCTL_ENTRY(MSHV_ROOT_HVCALL, VV_IOCTL_DEVICE | VV_IOCTL_PARTITION | VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_INITIALIZE_PARTITION, VV_IOCTL_PARTITION, 0),
    IOCTL_ENTRY(MSHV_CREATE_VP, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_SET_GUEST_MEMORY, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_IRQFD, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_IOEVENTFD, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_SET_MSI_ROUTING, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_GET_GPAP_ACCESS_BITMAP, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_CREATE_DEVICE, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_MODIFY_GPA_HOST_ACCESS, VV_IOCTL_PARTITION, EOPNOTSUPP),
    IOCTL_ENTRY(MSHV_IMPORT_ISOLATED_PAGES, VV_IOCTL_PARTITION, EOPNOTSUPP),
    IOCTL_ENTRY(MSHV_GET_GPAP_RANGE_ACCESS, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_SCRUB_PARTITION, VV_IOCTL_PARTITION, 0),
    IOCTL_ENTRY(MSHV_INSTALL_INTERCEPT, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_ASSERT_INTERRUPT, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_SET_PARTITION_PROPERTY, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_GET_PARTITION_PROPERTY, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_COMPLETE_ISOLATED_IMPORT, VV_IOCTL_PARTITION, EOPNOTSUPP),
    IOCTL_ENTRY(MSHV_ISSUE_PSP_GUEST_REQUEST, VV_IOCTL_PARTITION, EOPNOTSUPP),
    IOCTL_ENTRY(MSHV_SEV_SNP_AP_CREATE, VV_IOCTL_PARTITION, EOPNOTSUPP),
    IOCTL_ENTRY(MSHV_SIGNAL_EVENT_DIRECT, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_POST_MESSAGE_DIRECT, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_REGISTER_DELIVERABILITY_NOTIFICATIONS, VV_IOCTL_PARTITION, EFAULT),
    IOCTL_ENTRY(MSHV_RUN_VP, VV_IOCTL_VP, 0),
    IOCTL_ENTRY(MSHV_GET_VP_STATE, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_SET_VP_STATE, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_TRANSLATE_GVA, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_GET_VP_REGISTERS, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_SET_VP_REGISTERS, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_VP_REGISTER_INTERCEPT_RESULT, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_GET_VP_CPUID_VALUES, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_READ_GPA, VV_IOCTL_VP, EFAULT),
    IOCTL_ENTRY(MSHV_WRITE_GPA, VV_IOCTL_VP, EFAULT),
};

#undef IOCTL_ENTRY

const size_t mshv_ioctl_count = sizeof(mshv_ioctl_table) / sizeof(mshv_ioctl_table[0]);

test_result_t mshv_expect_ioctl(int fd, unsigned long request, void *arg,
                              const char *operation, int expected_errno)
{
    errno = 0;
    int rc = ioctl(fd, request, arg);
    int actual_errno = errno;
    if ((expected_errno == 0 && rc != 0) ||
        (expected_errno != 0 && (rc != -1 || actual_errno != expected_errno)))
        TFAIL("%s: expected rc=%d errno=%d (%s), actual rc=%d errno=%d (%s)",
              operation, expected_errno ? -1 : 0, expected_errno,
              strerror(expected_errno), rc, actual_errno, strerror(actual_errno));
    return TEST_PASS;
}

test_result_t mshv_close(int *fd, const char *operation)
{
    if (*fd < 0)
        return TEST_PASS;
    int owned = *fd;
    *fd = -1;
    if (close(owned) != 0)
        TFAIL("%s: close(%d) expected 0, actual -1 errno=%d (%s)",
              operation, owned, errno, strerror(errno));
    return TEST_PASS;
}

test_result_t mshv_cleanup(struct mshv_fixture *f)
{
    test_result_t result = TEST_PASS;
    if (mshv_close(&f->vp, "cleanup VP") != TEST_PASS)
        result = TEST_FAIL;
    if (mshv_close(&f->partition, "cleanup partition") != TEST_PASS)
        result = TEST_FAIL;
    if (mshv_close(&f->device, "cleanup device") != TEST_PASS)
        result = TEST_FAIL;
    return result;
}

test_result_t mshv_check_fd(int fd, const char *operation, ...)
{
    int actual_errno = errno;
    int flags = -1;
    if (fd >= 0) {
        flags = fcntl(fd, F_GETFD);
        actual_errno = flags < 0 ? errno : 0;
    }
    if (flags >= 0 && (flags & FD_CLOEXEC))
        return TEST_PASS;
    printf("vv-fail %s:%d: ", __FILE__, __LINE__);
    va_list args;
    va_start(args, operation);
    vprintf(operation, args);
    va_end(args);
    if (fd < 0)
        printf(": expected resource fd >= 0, actual %d errno=%d (%s)\n",
               fd, actual_errno, strerror(actual_errno));
    else
        printf(": fd=%d expected F_GETFD with FD_CLOEXEC, actual %d errno=%d\n",
               fd, flags, actual_errno);
    fflush(stdout);
    return TEST_FAIL;
}

test_result_t mshv_create(struct mshv_fixture *f)
{
    struct mshv_create_partition partition = {
        .pt_flags = VV_MSHV_PARTITION_FLAGS_NONE,
        .pt_isolation = MSHV_PT_ISOLATION_NONE,
    };
    struct mshv_create_vp vp = {.vp_index = 0};

    f->device = open("/dev/mshv", O_RDWR | O_CLOEXEC);
    if (mshv_check_fd(f->device, "open /dev/mshv") != TEST_PASS)
        return TEST_FAIL;
    f->partition = ioctl(f->device, MSHV_CREATE_PARTITION, &partition);
    if (mshv_check_fd(f->partition,
                      "MSHV_CREATE_PARTITION flags=0x%" PRIx64 " isolation=0x%" PRIx64,
                      (uint64_t)partition.pt_flags, (uint64_t)partition.pt_isolation) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION", 0) != TEST_PASS)
        return TEST_FAIL;
    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp);
    return mshv_check_fd(f->vp, "MSHV_CREATE_VP index=%u", vp.vp_index);
}
