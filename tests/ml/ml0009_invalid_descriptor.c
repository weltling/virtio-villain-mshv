/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0009 - Invalid file descriptor rejection across all defined IOCTLs.
 *
 * Verify that invoking any defined MSHV IOCTL on an invalid file descriptor
 * returns EBADF. Test both negative file descriptors and closed descriptors.
 *
 * Following all rejections, confirm operational continuity with a valid
 * four register roundtrip on active descriptors.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <string.h>
#include <unistd.h>

#include "lib/mshv.h"

static test_result_t invalid_descriptor(struct mshv_fixture *f)
{
    char op[128];

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    /* Check negative file descriptor */
    for (size_t i = 0; i < mshv_ioctl_count; ++i) {
        snprintf(op, sizeof(op), "%s on fd=-1", mshv_ioctl_table[i].name);
        if (mshv_expect_ioctl(-1, mshv_ioctl_table[i].request, NULL, op, EBADF) != TEST_PASS)
            return TEST_FAIL;
    }

    /* Check closed temporary file descriptor */
    int temp_fd = open("/dev/mshv", O_RDWR | O_CLOEXEC);
    if (temp_fd < 0)
        return TEST_FAIL;
    if (close(temp_fd) != 0)
        return TEST_FAIL;
    for (size_t i = 0; i < mshv_ioctl_count; ++i) {
        snprintf(op, sizeof(op), "%s on closed fd=%d", mshv_ioctl_table[i].name, temp_fd);
        if (mshv_expect_ioctl(temp_fd, mshv_ioctl_table[i].request, NULL, op, EBADF) != TEST_PASS)
            return TEST_FAIL;
    }

    return mshv_roundtrip(f, 4, VV_GPR_SEED_INVALID_DESCRIPTOR);
}

REGISTER_MSHV_TEST(ML0009, invalid_descriptor,
                   "Invalid file descriptor rejection across all defined IOCTLs");
