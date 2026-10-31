/* SPDX-License-Identifier: Apache-2.0 */
/*
 * TL0006: SynIC message and event pages are cleared at VP creation.
 *
 * TLFS 6.0b section 11.9 requires SIM and SIEF pages to be cleared at VP
 * creation and reset. Both pages contain sixteen 256 byte elements.
 * Requires a local APIC and SynIC page state access. No VP execution or message delivery.
 */
#include <errno.h>
#include <string.h>
#include <sys/mman.h>

#include "lib/mshv.h"

static test_result_t check_pages(struct mshv_fixture *f, uint8_t *page)
{
    const uint8_t types[] = {MSHV_VP_STATE_SIMP, MSHV_VP_STATE_SIEFP};
    for (unsigned i = 0; i < sizeof(types) / sizeof(types[0]); ++i) {
        memset(page, 0xa5, MSHV_HV_PAGE_SIZE);
        struct mshv_get_set_vp_state args = {
            .type = types[i],
            .buf_sz = MSHV_HV_PAGE_SIZE,
            .buf_ptr = (uintptr_t)page,
        };
        if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_STATE, &args, "read initial SynIC page", 0) != TEST_PASS)
            return TEST_FAIL;
        if (args.buf_sz != MSHV_HV_PAGE_SIZE)
            TFAIL("SynIC state type=%u: expected size=%u, actual=%u",
                  types[i], MSHV_HV_PAGE_SIZE, args.buf_sz);
        for (unsigned offset = 0; offset < MSHV_HV_PAGE_SIZE; ++offset) {
            if (page[offset] != 0)
                TFAIL("initial SynIC page type=%u offset=%u: expected zero, actual=0x%02x",
                      types[i], offset, page[offset]);
        }
    }
    return TEST_PASS;
}

static test_result_t synic_state(struct mshv_fixture *f)
{
    if (mshv_create_configured(f, 1U << MSHV_PT_BIT_LAPIC,
                               VV_TLFS_BASIC_FEATURES | VV_HV_FEATURE_SYNIC) != TEST_PASS)
        return TEST_FAIL;
    uint8_t *page = mmap(NULL, MSHV_HV_PAGE_SIZE, PROT_READ | PROT_WRITE,
                         MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (page == MAP_FAILED)
        TFAIL("allocate SynIC state buffer: errno=%d (%s)", errno, strerror(errno));
    test_result_t result = check_pages(f, page);
    if (munmap(page, MSHV_HV_PAGE_SIZE) != 0)
        TFAIL("release SynIC state buffer: errno=%d (%s)", errno, strerror(errno));
    return result;
}

REGISTER_MSHV_TEST(TL0006, synic_state,
                   "Initial SynIC message and event page contents",
                   TLFS_SPEC_V6_0B, "11.9");
