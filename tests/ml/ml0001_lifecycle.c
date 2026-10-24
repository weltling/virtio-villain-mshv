/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0001 - Create and use a partition and virtual processor (VP).
 *
 * UAPI: MSHV_CREATE_PARTITION, MSHV_INITIALIZE_PARTITION, MSHV_CREATE_VP.
 *
 * Open the device, create a partition, initialize it, then create VP zero.
 * Repeat initialization after VP creation. Both calls must return zero,
 * verifying idempotency. Set/get RAX must preserve VV_GPR_SEED_LIFECYCLE exactly,
 * demonstrating usable resources rather than just successful allocation.
 */
#include "lib/mshv.h"

static test_result_t lifecycle(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION repeated (idempotent)", 0) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 1, VV_GPR_SEED_LIFECYCLE);
}

REGISTER_MSHV_TEST(ML0001, lifecycle, "Create, initialize twice, create VP, use descriptors");
