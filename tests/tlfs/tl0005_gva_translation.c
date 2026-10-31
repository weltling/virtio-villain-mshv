/* SPDX-License-Identifier: Apache-2.0 */
/*
 * TL0005: Address translation and page permission results.
 *
 * TLFS 6.0b section 9.4 defines address translation. Section 9.3 defines
 * read and write validation flags and translation result codes.
 * MSHV additionally supplies explicit supervisor access context.
 * Requires 4 KiB pages and x86-64 paging state access. No VP execution.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>
#include <sys/mman.h>

#include "lib/mshv.h"

#define GUEST_BASE UINT64_C(0x10000)
#define VIRTUAL_BASE UINT64_C(0x200000)
#define PAGE_MASK UINT64_C(0xfff)

static test_result_t check_translation(struct mshv_fixture *f, uint64_t gva,
                                       uint64_t flags, enum hv_translate_gva_result_code expected,
                                       uint64_t expected_gpa)
{
    struct hv_input_translate_gva input = {
        .flags = flags,
        .gva_page = gva / MSHV_HV_PAGE_SIZE,
    };
    struct hv_output_translate_gva output;
    memset(&output, 0xa5, sizeof(output));
    struct mshv_root_hvcall hvcall = {
        .code = HVCALL_TRANSLATE_VIRTUAL_ADDRESS,
        .in_sz = sizeof(input),
        .out_sz = sizeof(output),
        .in_ptr = (uintptr_t)&input,
        .out_ptr = (uintptr_t)&output,
    };
    if (mshv_expect_hvcall(f->vp, &hvcall, "translate virtual page", VV_HVCALL_SUCCESS) != TEST_PASS)
        return TEST_FAIL;
    if ((uint32_t)output.result != (uint32_t)expected)
        TFAIL("hypercall translation GVA=0x%" PRIx64 ": expected result=%u, actual=%u",
              gva, (unsigned)expected, (unsigned)(uint32_t)output.result);
    if (expected == HV_TRANSLATE_GVA_SUCCESS &&
        output.gpa_page != expected_gpa / MSHV_HV_PAGE_SIZE)
        TFAIL("hypercall translation GVA=0x%" PRIx64 ": expected GPA page=0x%" PRIx64
              ", actual=0x%" PRIx64, gva, expected_gpa / MSHV_HV_PAGE_SIZE, output.gpa_page);

    enum hv_translate_gva_result_code result = (enum hv_translate_gva_result_code)UINT32_MAX;
    uint64_t gpa = UINT64_MAX;
    struct mshv_translate_gva args = {.gva = gva, .flags = flags, .result = &result, .gpa = &gpa};
    if (mshv_expect_ioctl(f->vp, MSHV_TRANSLATE_GVA, &args, "translate virtual address", 0) != TEST_PASS)
        return TEST_FAIL;
    if (result != expected)
        TFAIL("translation GVA=0x%" PRIx64 ": expected result=%u, actual=%u",
              gva, (unsigned)expected, (unsigned)result);
    if (expected == HV_TRANSLATE_GVA_SUCCESS && gpa != expected_gpa)
        TFAIL("translation GVA=0x%" PRIx64 ": expected GPA=0x%" PRIx64
              ", actual=0x%" PRIx64, gva, expected_gpa, gpa);
    return TEST_PASS;
}

static test_result_t check_page_tables(struct mshv_fixture *f)
{
    const struct hv_register_assoc mode[] = {
        {.name = VV_CR3, .value.reg64 = GUEST_BASE},
        {.name = VV_CR4, .value.reg64 = UINT64_C(0x20)},
        /* Register writes do not perform mode transition side effects. */
        {.name = VV_EFER, .value.reg64 = UINT64_C(0x500)},
        {.name = VV_CS, .value.segment = {
            .limit = UINT32_MAX, .selector = 8, .attributes = 0xa09b,
        }},
        {.name = VV_CR0, .value.reg64 = UINT64_C(0x80010033)},
    };
    if (mshv_set_registers(f->vp, 0, mode, sizeof(mode) / sizeof(mode[0])) != TEST_PASS)
        return TEST_FAIL;
    const struct {
        uint64_t offset;
        uint64_t access;
        enum hv_translate_gva_result_code result;
    } cases[] = {
        {0, HV_TRANSLATE_GVA_VALIDATE_READ, HV_TRANSLATE_GVA_SUCCESS},
        {0x321, HV_TRANSLATE_GVA_VALIDATE_READ, HV_TRANSLATE_GVA_SUCCESS},
        {PAGE_MASK, HV_TRANSLATE_GVA_VALIDATE_READ, HV_TRANSLATE_GVA_SUCCESS},
        {0x7d5, HV_TRANSLATE_GVA_VALIDATE_WRITE, HV_TRANSLATE_GVA_SUCCESS},
        {MSHV_HV_PAGE_SIZE + 0x345, HV_TRANSLATE_GVA_VALIDATE_READ, HV_TRANSLATE_GVA_SUCCESS},
        {MSHV_HV_PAGE_SIZE + 0x345, HV_TRANSLATE_GVA_VALIDATE_WRITE,
         HV_TRANSLATE_GVA_PRIVILEGE_VIOLATION},
        {2 * MSHV_HV_PAGE_SIZE + 0xabc, HV_TRANSLATE_GVA_VALIDATE_READ,
         HV_TRANSLATE_GVA_PAGE_NOT_PRESENT},
    };
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        if (check_translation(f, VIRTUAL_BASE + cases[i].offset,
                              HV_TRANSLATE_GVA_SUPERVISOR_ACCESS | cases[i].access,
                              cases[i].result, GUEST_BASE + 4 * MSHV_HV_PAGE_SIZE +
                              cases[i].offset) != TEST_PASS)
            return TEST_FAIL;
    }
    return TEST_PASS;
}

static test_result_t gva_translation(struct mshv_fixture *f)
{
    const size_t size = 6 * MSHV_HV_PAGE_SIZE;
    test_result_t result = TEST_FAIL;
    int mapped = 0;
    if (mshv_create_configured(f, VV_MSHV_PARTITION_FLAGS_NONE, VV_TLFS_BASIC_FEATURES) != TEST_PASS)
        return TEST_FAIL;
    uint64_t *memory = mmap(NULL, size, PROT_READ | PROT_WRITE,
                            MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (memory == MAP_FAILED)
        TFAIL("allocate guest page tables: errno=%d (%s)", errno, strerror(errno));
    memset(memory, 0, size);
    size_t entries = MSHV_HV_PAGE_SIZE / sizeof(*memory);
    memory[0] = (GUEST_BASE + MSHV_HV_PAGE_SIZE) | UINT64_C(3);
    memory[entries] = (GUEST_BASE + 2 * MSHV_HV_PAGE_SIZE) | UINT64_C(3);
    memory[2 * entries + 1] = (GUEST_BASE + 3 * MSHV_HV_PAGE_SIZE) | UINT64_C(3);
    memory[3 * entries] = (GUEST_BASE + 4 * MSHV_HV_PAGE_SIZE) | UINT64_C(3);
    memory[3 * entries + 1] = (GUEST_BASE + 5 * MSHV_HV_PAGE_SIZE) | UINT64_C(1);
    struct mshv_user_mem_region region = {
        .size = size,
        .guest_pfn = GUEST_BASE / MSHV_HV_PAGE_SIZE,
        .userspace_addr = (uintptr_t)memory,
        .flags = 1U << MSHV_SET_MEM_BIT_WRITABLE,
    };
    if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, &region,
                            "map guest page tables", 0) != TEST_PASS)
        goto out;
    mapped = 1;
    result = check_page_tables(f);
out:
    if (mapped) {
        region.flags = 1U << MSHV_SET_MEM_BIT_UNMAP;
        if (mshv_expect_ioctl(f->partition, MSHV_SET_GUEST_MEMORY, &region,
                                "unmap guest page tables", 0) != TEST_PASS)
            result = TEST_FAIL;
    }
    if (munmap(memory, size) != 0)
        TFAIL("release guest page tables: errno=%d (%s)", errno, strerror(errno));
    return result;
}

REGISTER_MSHV_TEST(TL0005, gva_translation,
                   "Address translation and page permission results",
                   TLFS_SPEC_V6_0B, "9.4");
