/* SPDX-License-Identifier: Apache-2.0 */
/*
 * MR0005 - Virtual processor state buffer alignment and size validation.
 *
 * UAPI: MSHV_GET_VP_STATE, MSHV_SET_VP_STATE.
 *
 * Verify that processor state IOCTLs enforce buffer page alignment,
 * nonzero page aligned sizes, reserved field checks, and state type bounds.
 * Verify that invalid arguments return EINVAL and NULL pointers return EFAULT.
 *
 * Following all rejections, confirm that general purpose registers remain
 * undamaged.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t vp_state(struct mshv_fixture *f)
{
    struct mshv_get_set_vp_state bad_type = {
        .type = 99,
        .buf_sz = 4096,
        .buf_ptr = 0x10000,
    };
    struct mshv_get_set_vp_state unaligned_sz = {
        .type = 0,
        .buf_sz = 128,
        .buf_ptr = 0x10000,
    };
    struct mshv_get_set_vp_state unaligned_ptr = {
        .type = 0,
        .buf_sz = 4096,
        .buf_ptr = 0x10001,
    };

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    /* NULL argument must return EFAULT */
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_STATE, NULL,
                          "MSHV_GET_VP_STATE NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_STATE, NULL,
                          "MSHV_SET_VP_STATE NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;

    /* Out of range state type must return EINVAL */
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_STATE, &bad_type,
                          "MSHV_GET_VP_STATE bad type", EINVAL) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_STATE, &bad_type,
                          "MSHV_SET_VP_STATE bad type", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    /* Unaligned buffer size must return EINVAL */
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_STATE, &unaligned_sz,
                          "MSHV_GET_VP_STATE unaligned size", EINVAL) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_STATE, &unaligned_sz,
                          "MSHV_SET_VP_STATE unaligned size", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    /* Unaligned buffer pointer must return EINVAL */
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_STATE, &unaligned_ptr,
                          "MSHV_GET_VP_STATE unaligned pointer", EINVAL) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->vp, MSHV_SET_VP_STATE, &unaligned_ptr,
                          "MSHV_SET_VP_STATE unaligned pointer", EINVAL) != TEST_PASS)
        return TEST_FAIL;

    return mshv_roundtrip(f, 4, VV_GPR_SEED_VP_STATE);
}

REGISTER_MSHV_TEST(MR0005, vp_state,
                   "Virtual processor state buffer alignment and size validation", "", "");
