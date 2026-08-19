/*
Copyright 2016 The Kubernetes Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package kamatera

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	apiv1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/autoscaler/cluster-autoscaler/cloudprovider"
	"k8s.io/autoscaler/cluster-autoscaler/utils/taints"
	"k8s.io/client-go/kubernetes/fake"
)

func TestInstance_refresh_PoweroffOnScaleDownClearsNodeMetadata(t *testing.T) {
	providerIDPrefix := "rke2://"
	serverName := mockKamateraServerName()
	serverProviderID := formatKamateraProviderID(providerIDPrefix, serverName)

	kubeClient := fake.NewSimpleClientset(&apiv1.Node{
		ObjectMeta: metav1.ObjectMeta{Name: serverName},
		Spec: apiv1.NodeSpec{
			Unschedulable: true,
			Taints: []apiv1.Taint{
				{Key: taints.ToBeDeletedTaint, Value: "123", Effect: apiv1.TaintEffectNoSchedule},
				{Key: taints.DeletionCandidateTaint().Key, Value: "123", Effect: apiv1.TaintEffectPreferNoSchedule},
				{Key: "custom", Value: "x", Effect: apiv1.TaintEffectNoSchedule},
			},
		},
	})

	client := kamateraClientMock{}
	ctx := context.Background()
	client.On("getCommandStatus", ctx, "cmd-poweroff").Return(CommandStatusComplete, nil).Once()

	instance := &Instance{
		Id:                serverProviderID,
		Status:            &cloudprovider.InstanceStatus{State: cloudprovider.InstanceDeleting},
		PowerOn:           false,
		StatusCommandId:   "cmd-poweroff",
		StatusCommandCode: InstanceCommandPoweroff,
	}

	needToDelete, needToHandleScaleDown := instance.refresh(&client, providerIDPrefix, true)
	assert.False(t, needToDelete)
	assert.True(t, needToHandleScaleDown)
	assert.True(t, instance.handleScaleDown(true, 0, 0, kubeClient, &client, providerIDPrefix))
	assert.Nil(t, instance.Status)
	assert.True(t, instance.requiresNodeBeforeAdoption)

	node, err := kubeClient.CoreV1().Nodes().Get(ctx, serverName, metav1.GetOptions{})
	assert.NoError(t, err)
	assert.False(t, node.Spec.Unschedulable)
	assert.False(t, taints.HasTaint(node, taints.ToBeDeletedTaint))
	assert.False(t, taints.HasTaint(node, taints.DeletionCandidateTaint().Key))
	assert.True(t, taints.HasTaint(node, "custom"))
}

func TestInstance_refresh_PoweronCompleteWhilePoweredOffMarksRunning(t *testing.T) {
	providerIDPrefix := "rke2://"
	serverName := mockKamateraServerName()
	serverProviderID := formatKamateraProviderID(providerIDPrefix, serverName)
	client := kamateraClientMock{}
	ctx := context.Background()
	client.On("getCommandStatus", ctx, "cmd-poweron").Return(CommandStatusComplete, nil).Once()
	instance := &Instance{
		Id:                serverProviderID,
		Status:            &cloudprovider.InstanceStatus{State: cloudprovider.InstanceCreating},
		PowerOn:           false,
		StatusCommandId:   "cmd-poweron",
		StatusCommandCode: InstanceCommandPoweron,
	}

	needToDelete, needToHandleScaleDown := instance.refresh(&client, providerIDPrefix, true)

	assert.False(t, needToDelete)
	assert.False(t, needToHandleScaleDown)
	if assert.NotNil(t, instance.Status) {
		assert.Equal(t, cloudprovider.InstanceRunning, instance.Status.State)
		assert.Nil(t, instance.Status.ErrorInfo)
	}
	assert.False(t, instance.PowerOn)
	assert.False(t, instance.requiresNodeBeforeAdoption)
	assert.False(t, instance.countsTowardTarget())
	assert.False(t, instance.visibleToAutoscaler())
	assert.Equal(t, "", instance.StatusCommandId)
	assert.Equal(t, InstanceCommandNone, instance.StatusCommandCode)
}

func TestInstance_createPoweronClearsNodeAdoptionRequirement(t *testing.T) {
	providerIDPrefix := "rke2://"
	serverName := mockKamateraServerName()
	client := kamateraClientMock{}
	client.On("StartServerRequest", context.Background(), ServerRequestPoweron, serverName).Return("cmd-poweron", nil).Once()
	instance := &Instance{
		Id:                         formatKamateraProviderID(providerIDPrefix, serverName),
		PowerOn:                    false,
		requiresNodeBeforeAdoption: true,
	}

	err := instance.createPoweron(&client, providerIDPrefix)

	assert.NoError(t, err)
	assert.False(t, instance.requiresNodeBeforeAdoption)
	assert.NotNil(t, instance.Status)
	assert.Equal(t, cloudprovider.InstanceCreating, instance.Status.State)
	assert.Equal(t, "cmd-poweron", instance.StatusCommandId)
}

func TestInstance_deleteRetainedPoweredOffServerRequiresNodeBeforeAdoption(t *testing.T) {
	instance := &Instance{
		Id:      "rke2://server1",
		PowerOn: false,
		Status:  &cloudprovider.InstanceStatus{State: cloudprovider.InstanceRunning},
	}

	err := instance.delete(&kamateraClientMock{}, "rke2://", true)

	assert.NoError(t, err)
	assert.Nil(t, instance.Status)
	assert.True(t, instance.requiresNodeBeforeAdoption)
}

func TestInstance_refresh_PoweredOffRunningInstanceRequiresNodeBeforeAdoption(t *testing.T) {
	instance := &Instance{
		Id:      "rke2://server1",
		PowerOn: false,
		Status:  &cloudprovider.InstanceStatus{State: cloudprovider.InstanceRunning},
	}

	needToDelete, needToHandleScaleDown := instance.refresh(&kamateraClientMock{}, "rke2://", true)

	assert.False(t, needToDelete)
	assert.False(t, needToHandleScaleDown)
	assert.Nil(t, instance.Status)
	assert.True(t, instance.requiresNodeBeforeAdoption)
}

func TestInstance_refresh_UnexpectedCommandCompletePoweredOffMarksRunning(t *testing.T) {
	client := kamateraClientMock{}
	client.On("getCommandStatus", context.Background(), "cmd-unknown").Return(CommandStatusComplete, nil).Once()
	instance := &Instance{
		Id:                "rke2://server1",
		PowerOn:           false,
		Status:            &cloudprovider.InstanceStatus{State: cloudprovider.InstanceCreating},
		StatusCommandId:   "cmd-unknown",
		StatusCommandCode: InstanceCommandNone,
	}

	needToDelete, needToHandleScaleDown := instance.refresh(&client, "rke2://", true)

	assert.False(t, needToDelete)
	assert.False(t, needToHandleScaleDown)
	if assert.NotNil(t, instance.Status) {
		assert.Equal(t, cloudprovider.InstanceRunning, instance.Status.State)
		assert.Nil(t, instance.Status.ErrorInfo)
	}
	assert.False(t, instance.PowerOn)
	assert.False(t, instance.requiresNodeBeforeAdoption)
	assert.False(t, instance.countsTowardTarget())
	assert.False(t, instance.visibleToAutoscaler())
	assert.Equal(t, "", instance.StatusCommandId)
	assert.Equal(t, InstanceCommandNone, instance.StatusCommandCode)
}

func TestInstance_refresh_CreateCompleteWhilePoweredOffMarksRunning(t *testing.T) {
	providerIDPrefix := "rke2://"
	serverName := mockKamateraServerName()
	serverProviderID := formatKamateraProviderID(providerIDPrefix, serverName)
	client := kamateraClientMock{}
	ctx := context.Background()
	client.On("getCommandStatus", ctx, "cmd-create").Return(CommandStatusComplete, nil).Once()
	instance := &Instance{
		Id:                serverProviderID,
		Status:            &cloudprovider.InstanceStatus{State: cloudprovider.InstanceCreating},
		PowerOn:           false,
		StatusCommandId:   "cmd-create",
		StatusCommandCode: InstanceCommandCreating,
	}

	needToDelete, needToHandleScaleDown := instance.refresh(&client, providerIDPrefix, true)

	assert.False(t, needToDelete)
	assert.False(t, needToHandleScaleDown)
	if assert.NotNil(t, instance.Status) {
		assert.Equal(t, cloudprovider.InstanceRunning, instance.Status.State)
		assert.Nil(t, instance.Status.ErrorInfo)
	}
	assert.False(t, instance.PowerOn)
	assert.False(t, instance.requiresNodeBeforeAdoption)
	assert.False(t, instance.countsTowardTarget())
	assert.False(t, instance.visibleToAutoscaler())
	assert.Equal(t, "", instance.StatusCommandId)
	assert.Equal(t, InstanceCommandNone, instance.StatusCommandCode)
}

func TestInstance_refresh_CommandStatusRequestErrorIsRetried(t *testing.T) {
	client := kamateraClientMock{}
	client.On("getCommandStatus", context.Background(), "cmd-create").
		Return(CommandStatusPending, errors.New("temporary API error")).Once()
	instance := &Instance{
		Id:                "rke2://server1",
		PowerOn:           false,
		Status:            &cloudprovider.InstanceStatus{State: cloudprovider.InstanceCreating},
		StatusCommandId:   "cmd-create",
		StatusCommandCode: InstanceCommandCreating,
	}

	needToDelete, needToHandleScaleDown := instance.refresh(&client, "rke2://", true)

	assert.False(t, needToDelete)
	assert.False(t, needToHandleScaleDown)
	if assert.NotNil(t, instance.Status) {
		assert.Equal(t, cloudprovider.InstanceCreating, instance.Status.State)
		assert.Nil(t, instance.Status.ErrorInfo)
	}
	assert.Equal(t, "cmd-create", instance.StatusCommandId)
	assert.Equal(t, InstanceCommandCreating, instance.StatusCommandCode)
	assert.True(t, instance.countsTowardTarget())
	assert.True(t, instance.visibleToAutoscaler())
}
