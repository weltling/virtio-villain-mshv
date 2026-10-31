/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0012 - Uninitialized partition rejection and idempotent initialization.
 *
 * UAPI: MSHV_CREATE_PARTITION, MSHV_INITIALIZE_PARTITION, MSHV_CREATE_VP.
 *
 * Verify that creating a virtual processor on a partition that has not
 * yet been initialized returns EINVAL. Verify that initializing the
 * partition succeeds and repeated initialization is idempotent. Verify
 * that virtual processor creation succeeds after initialization.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t uninitialized_partition(struct mshv_fixture *f)
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
    if (mshv_check_fd(f->partition, "MSHV_CREATE_PARTITION") != TEST_PASS)
        return TEST_FAIL;

    /* VP creation before initialization must fail with hypervisor EIO */
    if (mshv_expect_ioctl(f->partition, MSHV_CREATE_VP, &vp,
                          "MSHV_CREATE_VP on uninitialized partition", EIO) != TEST_PASS)
        return TEST_FAIL;

    /* Initialize partition */
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION first", 0) != TEST_PASS)
        return TEST_FAIL;

    /* Repeated initialization must be idempotent and return zero */
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION second", 0) != TEST_PASS)
        return TEST_FAIL;

    /* VP creation must succeed after initialization */
    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp);
    if (mshv_check_fd(f->vp, "MSHV_CREATE_VP after initialization") != TEST_PASS)
        return TEST_FAIL;

    return mshv_roundtrip(f, 4, VV_GPR_SEED_UNINITIALIZED_PARTITION);
}

REGISTER_MSHV_TEST(ML0012, uninitialized_partition,
                   "Uninitialized partition rejection and idempotent initialization", "", "");
