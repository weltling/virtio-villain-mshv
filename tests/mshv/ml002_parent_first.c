/* SPDX-License-Identifier: Apache-2.0 */
#include "mshv/test.h"

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

REGISTER_MSHV_TEST(ML002, parent_first, "VP register access after closing both parent descriptors");
