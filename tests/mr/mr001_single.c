/* SPDX-License-Identifier: Apache-2.0 */
#include "mshv/test.h"

static test_result_t single(struct mshv_fixture *f)
{
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    const uint64_t values[] = {0, UINT64_MAX, 0x8000000000000001ULL,
                               0x0123456789abcdefULL};
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); ++i)
        if (mshv_roundtrip(f, 1, values[i]) != TEST_PASS)
            return TEST_FAIL;
    return TEST_PASS;
}

REGISTER_MSHV_TEST(MR001, single, "single RAX roundtrips including all bits set");
