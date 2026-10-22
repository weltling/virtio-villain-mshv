/* SPDX-License-Identifier: Apache-2.0 */
#include "mshv/test.h"

static test_result_t lifecycle(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_INITIALIZE_PARTITION, NULL,
                          "MSHV_INITIALIZE_PARTITION repeated (idempotent)", 0) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 1, 0x123456789abcdef0ULL);
}

REGISTER_MSHV_TEST(ML001, lifecycle, "create, initialize twice, create VP, use descriptors");
