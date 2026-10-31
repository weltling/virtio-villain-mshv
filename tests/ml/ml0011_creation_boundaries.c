/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0011 - Partition and virtual processor creation boundary checks.
 *
 * UAPI: MSHV_CREATE_PARTITION, MSHV_CREATE_VP.
 *
 * Verify that partition creation rejects reserved flag bits and out
 * of range isolation values with EINVAL. Verify that virtual processor
 * creation rejects indices beyond the supported limit with EINVAL.
 *
 * Following all rejections, confirm that valid creation succeeds and
 * general purpose registers operate normally.
 */
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

enum {
    MSHV_MAX_VPS_LIMIT = 256,
};

static test_result_t creation_boundaries(struct mshv_fixture *f)
{
    struct mshv_create_partition bad_flags = {
        .pt_flags = ~MSHV_PT_FLAGS_MASK,
        .pt_isolation = MSHV_PT_ISOLATION_NONE,
    };
    struct mshv_create_partition bad_isolation = {
        .pt_flags = VV_MSHV_PARTITION_FLAGS_NONE,
        .pt_isolation = MSHV_PT_ISOLATION_COUNT,
    };
    struct mshv_create_partition valid_partition = {
        .pt_flags = VV_MSHV_PARTITION_FLAGS_NONE,
        .pt_isolation = MSHV_PT_ISOLATION_NONE,
    };
    struct mshv_create_vp vp_limit = {.vp_index = MSHV_MAX_VPS_LIMIT};
    struct mshv_create_vp vp_huge = {.vp_index = UINT32_MAX};
    struct mshv_create_vp vp_zero = {.vp_index = 0};

    f->device = open("/dev/mshv", O_RDWR | O_CLOEXEC);
    if (mshv_check_fd(f->device, "open /dev/mshv") != TEST_PASS)
        return TEST_FAIL;

    if (mshv_expect_ioctl(f->device, MSHV_CREATE_PARTITION, &bad_flags,
                          "MSHV_CREATE_PARTITION bad flags", EINVAL) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->device, MSHV_CREATE_PARTITION, &bad_isolation,
                          "MSHV_CREATE_PARTITION bad isolation", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    f->partition = ioctl(f->device, MSHV_CREATE_PARTITION, &valid_partition);
    if (mshv_check_fd(f->partition, "MSHV_CREATE_PARTITION valid") != TEST_PASS)
        return TEST_FAIL;

    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION", 0) != TEST_PASS)
        return TEST_FAIL;

    if (mshv_expect_ioctl(f->partition, MSHV_CREATE_VP, &vp_limit,
                          "MSHV_CREATE_VP index=256", EINVAL) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_CREATE_VP, &vp_huge,
                          "MSHV_CREATE_VP index=UINT32_MAX", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp_zero);
    if (mshv_check_fd(f->vp, "MSHV_CREATE_VP index=0") != TEST_PASS)
        return TEST_FAIL;

    return mshv_roundtrip(f, 4, VV_GPR_SEED_CREATION_BOUNDARIES);
}

REGISTER_MSHV_TEST(ML0011, creation_boundaries,
                   "Creation parameter boundary rejection for partitions and processors", "", "");
