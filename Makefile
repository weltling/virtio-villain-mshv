# SPDX-License-Identifier: Apache-2.0
CC = gcc
RUSTC = false
CFLAGS ?= -static -O2 -Wall -Wextra -Werror
LDFLAGS ?= -static
TARGET ?= target
MSHV_SOURCE ?= $(HOME)/linux
SUITE_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VV_ROOT ?= $(abspath $(SUITE_ROOT)/../virtio-villain)
KERNEL_CONFIGS ?=
KERNEL_ARGS ?=

.DEFAULT_GOAL := initramfs

contract:
	python3 lib/contract.py --source "$(MSHV_SOURCE)" --output "$(TARGET)/mshv/contract.h"

init: contract
	sources="$$(python3 "$(SUITE_ROOT)/lib/sources.py" "$(CURDIR)")" && \
	$(MAKE) -C "$(VV_ROOT)" appliance CC="$(CC)" \
	  APPLIANCE_SRCS="$$sources" \
	  APPLIANCE_TARGET="$(abspath $(TARGET))/mshv" \
	  APPLIANCE_CPPFLAGS="-I$(CURDIR) -I$(abspath $(TARGET))/mshv" \
	  CFLAGS="$(CFLAGS)" LDFLAGS="$(LDFLAGS)"

initramfs: init
	python3 "$(VV_ROOT)/lib/python/villain/initramfs.py" --init "$(TARGET)/mshv/init" \
	  --output "$(TARGET)/mshv/initramfs.cpio.gz"

mshv mshv-initramfs: initramfs

kernel:
	RUSTC="$(RUSTC)" "$(VV_ROOT)/build-kernel" --source "$(MSHV_SOURCE)" \
	  $(if $(strip $(KERNEL_CONFIGS)),$(foreach config,$(KERNEL_CONFIGS),--config "$(config)"),--config "$(MSHV_SOURCE)/Microsoft/configs/x86/mshv_defconfig") \
	  --output "$(abspath $(TARGET))/kernel-microsoft" \
	  --cache-dir "$(abspath $(TARGET))/kernel-cache" --offline --jobs "$$(nproc)" \
	  $(KERNEL_ARGS)

clean:
	python3 "$(VV_ROOT)/lib/python/villain/clean.py" --root "$(CURDIR)" "$(TARGET)"

selftest:
	python3 -m unittest discover -s selftest -p 'test_*.py'

lint:
	python3 -m flake8 run-mshv lib selftest

help:
	@echo "Targets:"
	@echo "  init                Build the MSHV test executable"
	@echo "  initramfs           Build and package the executable as /init (default)"
	@echo "  mshv, mshv-initramfs Aliases for initramfs"
	@echo "  contract            Generate the selected source UAPI contract header"
	@echo "  kernel              Build the selected Linux source offline"
	@echo "  selftest            Run host tests without booting an appliance"
	@echo "  lint                Run Python lint"
	@echo "  clean               Remove the entire selected output directory"
	@echo "  help                Show this message"
	@echo ""
	@echo "Build variables:"
	@echo "  VV_ROOT             Framework checkout (current: $(VV_ROOT))"
	@echo "  MSHV_SOURCE         Kernel source checkout (current: $(MSHV_SOURCE))"
	@echo "  TARGET              Output directory (default: target)"
	@echo "  CC, CFLAGS, LDFLAGS  C compiler and build flags"
	@echo "  V=1                 Print compiler commands in framework and kernel builds"
	@echo "  KERNEL_CONFIGS      Ordered config files or fragments"
	@echo "                      Empty uses $(MSHV_SOURCE)/Microsoft/configs/x86/mshv_defconfig"
	@echo "                      A nonempty list replaces the default config"
	@echo "                      Later files override earlier values"
	@echo "  KERNEL_ARGS         Extra build-kernel options, processed after KERNEL_CONFIGS"
	@echo "                      Use --output DIR for a different config or toolchain"
	@echo "                      Use --jobs N to override the CPU count"
	@echo "  RUSTC               Kernel Rust compiler (default: false for the Microsoft C config)"
	@echo "                      Set RUSTC=rustc for a compatible custom Rust config"
	@echo ""
	@echo "Examples:"
	@echo '  make -j init initramfs kernel'
	@echo '  make kernel KERNEL_CONFIGS="/path/base.config /path/extra.config" KERNEL_ARGS="--output /path/custom-kernel"'
	@echo '  $(VV_ROOT)/build-kernel --help lists all generic kernel build options'
	@echo ""
	@echo "Relative paths are resolved from this suite directory."
	@echo "clean also removes cached boot components, kernel caches and saved results in TARGET."
	@echo "Keep reusable boot inputs outside TARGET and select them with MSHV_ESP."
	@echo "Use the framework run --suite PATH --help for execution options."

.PHONY: contract init initramfs mshv mshv-initramfs kernel clean selftest lint help
