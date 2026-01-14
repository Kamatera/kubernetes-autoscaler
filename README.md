# Kamatera Kubernetes Autoscaler

This is a fork of kubernetes/autoscaler with changes related to Kamatera Cloud Provider.

All Kamatera-specific changes are in branches prefixed with `kamatera-`:

* `kamatera-cluster-autoscaler`: Tracks the main autoscaler repository, focus on the cluster autoscaler component.
* `kamatera-cluster-autoscaler-release-X.Y`: Release branches for the Kamatera cluster autoscaler

Changes from upstream are rebased onto these branches.

## Cluster Autoscaler

See [cluster-autoscaler/cloudprovider/kamatera/README.md](cluster-autoscaler/cloudprovider/kamatera/README.md)
