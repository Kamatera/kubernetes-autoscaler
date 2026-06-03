# Kamatera Kubernetes Autoscaler

This is a fork of kubernetes/autoscaler with changes related to Kamatera Cloud Provider.

All Kamatera-specific changes are in branches prefixed with `kamatera-`:

* `kamatera-cluster-autoscaler`: Tracks the main autoscaler repository, focus on the cluster autoscaler component.
* `kamatera-cluster-autoscaler-release-X.Y`: Release branches for the Kamatera cluster autoscaler

Changes from upstream are rebased onto these branches.

## Integration Tests

Tests run on every push to `kamatera-cluster-autoscaler-*` branches with various configurations and environments from `.github/workflows/ca-kamatera.yaml`

Release branches run on the related kubernetes / autoscaler version.

The tests use real Kamatera infra and create a lot of servers so they will be expensive to run.

The tests depend on infra and code from https://github.com/Kamatera/kamatera-rke2-kubernetes-terraform-example 

### Running manually

See `.github/workflows/ca-kamatera.yaml`

### Cleaning-Up

Sometimes resources are not cleaned up properly, to cleanup see - 

https://github.com/Kamatera/kamatera-rke2-kubernetes-terraform-example/blob/main/tests/README.md 

## Cluster Autoscaler

See [cluster-autoscaler/cloudprovider/kamatera/README.md](cluster-autoscaler/cloudprovider/kamatera/README.md)
