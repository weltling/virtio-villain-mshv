/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <unistd.h>

#include "mshv/test.h"

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

test_result_t mshv_check_fd(int fd, const char *operation)
{
    if (fd < 0)
        TFAIL("%s: expected resource fd >= 0, actual %d errno=%d (%s)",
              operation, fd, errno, strerror(errno));
    int flags = fcntl(fd, F_GETFD);
    if (flags < 0 || !(flags & FD_CLOEXEC))
        TFAIL("%s: fd=%d expected F_GETFD with FD_CLOEXEC, actual %d errno=%d",
              operation, fd, flags, errno);
    return TEST_PASS;
}

test_result_t mshv_create(struct mshv_fixture *f)
{
    struct mshv_create_partition partition = {0};
    struct mshv_create_vp vp = {.vp_index = 0};

    f->device = open("/dev/mshv", O_RDWR | O_CLOEXEC);
    if (mshv_check_fd(f->device, "open /dev/mshv") != TEST_PASS)
        return TEST_FAIL;
    f->partition = ioctl(f->device, MSHV_CREATE_PARTITION, &partition);
    if (mshv_check_fd(f->partition, "MSHV_CREATE_PARTITION flags=0 isolation=0") != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION", 0) != TEST_PASS)
        return TEST_FAIL;
    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp);
    return mshv_check_fd(f->vp, "MSHV_CREATE_VP index=0");
}
