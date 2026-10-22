/* SPDX-License-Identifier: Apache-2.0 */
#include "mshv/test.h"

static test_result_t batch(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_roundtrip(f, 4, 0x0123456789abcdefULL) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 4, 0xfedcba9876543210ULL);
}

REGISTER_MSHV_TEST(MR002, batch, "four-register GPR batches with distinct exact values");
