/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0014 - Guest memory region mapping parameter boundary checks.
 *
 * UAPI: MSHV_SET_GUEST_MEMORY.
 *
 * Verify that memory region mapping rejects unaligned sizes, unaligned
 * userspace addresses, zero sizes, and reserved flag bits with EINVAL.
 * Verify that NULL arguments return EFAULT.
 *
 * Following all rejections, confirm that general purpose registers remain
 * undamaged.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t guest_memory(struct mshv_fixture *f)
{
    struct mshv_user_mem_region zero_size = {
        .size = 0,
        .guest_pfn = 0x1000,
        .userspace_addr = 0x10000,
    };
    struct mshv_user_mem_region unaligned_size = {
        .size = 4095,
        .guest_pfn = 0x1000,
        .userspace_addr = 0x10000,
    };
    struct mshv_user_mem_region unaligned_addr = {
        .size = 4096,
        .guest_pfn = 0x1000,
        .userspace_addr = 0x10001,
    };
    struct mshv_user_mem_region bad_flags = {
        .size = 4096,
        .guest_pfn = 0x1000,
        .userspace_addr = 0x10000,
        .flags = 0xf0,
    };

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    /* NULL argument must return EFAULT */
    if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, NULL,
                          "MSHV_SET_GUEST_MEMORY NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;

    /* Zero size must return EINVAL */
    if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, &zero_size,
                          "MSHV_SET_GUEST_MEMORY zero size", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    /* Unaligned size must return EINVAL */
    if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, &unaligned_size,
                          "MSHV_SET_GUEST_MEMORY unaligned size", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    /* Unaligned address must return EINVAL */
    if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, &unaligned_addr,
                          "MSHV_SET_GUEST_MEMORY unaligned address", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    /* Reserved flags must return EINVAL */
    if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, &bad_flags,
                          "MSHV_SET_GUEST_MEMORY bad flags", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    return mshv_roundtrip(f, 4, VV_GPR_SEED_GUEST_MEMORY);
}

REGISTER_MSHV_TEST(ML0014, guest_memory,
                   "Guest memory mapping alignment and size boundary checks");
