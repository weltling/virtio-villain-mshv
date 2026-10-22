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

static test_result_t check_fd(int fd, const char *operation)
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
    if (check_fd(f->device, "open /dev/mshv") != TEST_PASS)
        return TEST_FAIL;
    f->partition = ioctl(f->device, MSHV_CREATE_PARTITION, &partition);
    if (check_fd(f->partition, "MSHV_CREATE_PARTITION flags=0 isolation=0") != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION", 0) != TEST_PASS)
        return TEST_FAIL;
    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp);
    return check_fd(f->vp, "MSHV_CREATE_VP index=0");
}

static test_result_t lifecycle(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION repeated (idempotent)", 0) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 1, 0x123456789abcdef0ULL);
}

static test_result_t parent_first(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_close(&f->device, "close device before partition") != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "partition remains usable after device close", 0) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_close(&f->partition, "close partition before VP") != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 1, 0xfedcba9876543210ULL);
}

static test_result_t vp_first(struct mshv_fixture *f)
{
    struct mshv_create_vp vp = {.vp_index = 0};
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_close(&f->vp, "close VP before partition") != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_CREATE_VP, &vp,
                          "closed VP remains allocated until partition destruction",
                          EEXIST) != TEST_PASS)
        return TEST_FAIL;
    vp.vp_index = 1;
    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp);
    if (check_fd(f->vp, "MSHV_CREATE_VP index=1 after EEXIST") != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 1, 0x1020304050607080ULL);
}

static test_result_t repeated(struct mshv_fixture *f)
{
    for (unsigned i = 0; i < 128; ++i) {
        printf("mshv-cycle %u/128\n", i + 1);
        if ((i % 2 ? parent_first(f) : lifecycle(f)) != TEST_PASS)
            return TEST_FAIL;
        if (mshv_cleanup(f) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

REGISTER_MSHV_TEST(ML001, lifecycle, "create, initialize twice, create VP, use descriptors");
REGISTER_MSHV_TEST(ML002, parent_first, "VP register access after closing both parent descriptors");
REGISTER_MSHV_TEST(ML003, vp_first, "VP-first closure, exact EEXIST, then usable new VP");
REGISTER_MSHV_TEST(ML004, repeated, "128 lifecycle cycles alternating parent closure orders");
