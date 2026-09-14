PACKAGE := one-vyos-vrouter
VERSION ?= 0.2.0
RELEASE ?= 1

.PHONY: test deb clean

test:
	pytest -q

deb:
	VERSION=$(VERSION) RELEASE=$(RELEASE) ./packaging/build-deb.sh

clean:
	rm -rf out .pytest_cache **/__pycache__
