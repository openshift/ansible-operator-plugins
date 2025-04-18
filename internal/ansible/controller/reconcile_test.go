// Copyright 2018 The Operator-SDK Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package controller_test

import (
	"context"
	"reflect"
	"testing"
	"time"

	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	fakeclient "sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/controller"
	ansiblestatus "github.com/operator-framework/ansible-operator-plugins/internal/ansible/controller/status"
	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/events"
	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/runner"
	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/runner/eventapi"
	"github.com/operator-framework/ansible-operator-plugins/internal/ansible/runner/fake"
)

// The behaviour of fake client has changed with
// status subresources (ref: https://github.com/kubernetes-sigs/controller-runtime/pull/2259).
// (Tech Debt) This should be rewritten to use envtest to avoid any more breaking
// complications in future which include removal of fake client.
func TestReconcile(t *testing.T) {
	gvk := schema.GroupVersionKind{
		Kind:    "Testing",
		Group:   "operator-sdk",
		Version: "v1beta1",
	}
	eventTime := time.Now()
	testCases := []struct {
		Name            string
		GVK             schema.GroupVersionKind
		ReconcilePeriod time.Duration
		Runner          runner.Runner
		EventHandlers   []events.EventHandler
		Client          client.Client
		ExpectedObject  *unstructured.Unstructured
		Result          reconcile.Result
		Request         reconcile.Request
		ShouldError     bool
		ManageStatus    bool
	}{
		{
			Name:            "cr not found",
			GVK:             gvk,
			ReconcilePeriod: 5 * time.Second,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{},
			},
			Client: fakeclient.NewClientBuilder().Build(),
			Result: reconcile.Result{},
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "not_found",
					Namespace: "default",
				},
			},
		},
		{
			Name:            "completed reconcile",
			GVK:             gvk,
			ReconcilePeriod: 5 * time.Second,
			ManageStatus:    true,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Event:   eventapi.EventPlaybookOnStats,
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
				},
			}, true),
			Result: reconcile.Result{
				RequeueAfter: 5 * time.Second,
			},
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
			ExpectedObject: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"status": "True",
								"type":   "Running",
								"ansibleResult": map[string]interface{}{
									"changed":    int64(0),
									"failures":   int64(0),
									"ok":         int64(0),
									"skipped":    int64(0),
									"completion": eventTime.Format("2006-01-02T15:04:05.99999999+00:00"),
								},
								"message": "Awaiting next reconciliation",
								"reason":  "Successful",
							},
							map[string]interface{}{
								"status":  "True",
								"type":    "Successful",
								"message": "Last reconciliation succeeded",
								"reason":  "Successful",
							},
							map[string]interface{}{
								"status": "False",
								"type":   "Failure",
							},
						},
					},
				},
			},
		},
		{
			Name:         "Failure event runner on failed with manageStatus == true",
			GVK:          gvk,
			ManageStatus: true,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Event:   eventapi.EventRunnerOnFailed,
						Created: eventapi.EventTime{Time: eventTime},
						EventData: map[string]interface{}{
							"res": map[string]interface{}{
								"msg": "new failure message",
							},
						},
					},
					{
						Event:   eventapi.EventPlaybookOnStats,
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
				},
			}, true),
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
			ExpectedObject: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"status":  "False",
								"type":    "Running",
								"message": "Running reconciliation",
								"reason":  "Running",
							},
							map[string]interface{}{
								"status": "True",
								"type":   "Failure",
								"ansibleResult": map[string]interface{}{
									"changed":    int64(0),
									"failures":   int64(0),
									"ok":         int64(0),
									"skipped":    int64(0),
									"completion": eventTime.Format("2006-01-02T15:04:05.99999999+00:00"),
								},
								"message": "new failure message",
								"reason":  "Failed",
							},
							map[string]interface{}{
								"status": "False",
								"type":   "Successful",
							},
						},
					},
				},
			},
			ShouldError: true,
		},
		{
			Name:         "Failure event runner on failed",
			GVK:          gvk,
			ManageStatus: false,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Event:   eventapi.EventRunnerOnFailed,
						Created: eventapi.EventTime{Time: eventTime},
						EventData: map[string]interface{}{
							"res": map[string]interface{}{
								"msg": "new failure message",
							},
						},
					},
					{
						Event:   eventapi.EventPlaybookOnStats,
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
				},
			}, true),
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
			ShouldError: true,
		},
		{
			Name:            "Finalizer successful reconcile",
			GVK:             gvk,
			ReconcilePeriod: 5 * time.Second,
			ManageStatus:    true,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Event:   eventapi.EventPlaybookOnStats,
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
				Finalizer: "testing.io/finalizer",
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
						"annotations": map[string]interface{}{
							controller.ReconcilePeriodAnnotation: "3s",
						},
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
				},
			}, true),
			Result: reconcile.Result{
				RequeueAfter: 3 * time.Second,
			},
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
			ExpectedObject: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
						"annotations": map[string]interface{}{
							controller.ReconcilePeriodAnnotation: "3s",
						},
						"finalizers": []interface{}{
							"testing.io/finalizer",
						},
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"status": "True",
								"type":   "Running",
								"ansibleResult": map[string]interface{}{
									"changed":    int64(0),
									"failures":   int64(0),
									"ok":         int64(0),
									"skipped":    int64(0),
									"completion": eventTime.Format("2006-01-02T15:04:05.99999999+00:00"),
								},
								"message": "Awaiting next reconciliation",
								"reason":  "Successful",
							},
							map[string]interface{}{
								"status":  "True",
								"type":    "Successful",
								"message": "Last reconciliation succeeded",
								"reason":  "Successful",
							},
							map[string]interface{}{
								"status": "False",
								"type":   "Failure",
							},
						},
					},
				},
			},
		},
		{
			Name:            "Finalizer successful deletion reconcile",
			GVK:             gvk,
			ReconcilePeriod: 5 * time.Second,
			ManageStatus:    true,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Event:   eventapi.EventPlaybookOnStats,
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
				Finalizer: "testing.io/finalizer",
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
						"finalizers": []interface{}{
							"testing.io/finalizer",
						},
						"deletionTimestamp": eventTime.Format(time.RFC3339),
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"status": "True",
								"type":   "Running",
								"ansibleResult": map[string]interface{}{
									"changed":    int64(0),
									"failures":   int64(0),
									"ok":         int64(0),
									"skipped":    int64(0),
									"completion": eventTime.Format("2006-01-02T15:04:05.99999999+00:00"),
								},
								"message": "Awaiting next reconciliation",
								"reason":  "Successful",
							},
						},
					},
				},
			}, true),
			Result: reconcile.Result{
				RequeueAfter: 5 * time.Second,
			},
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
		},
		{
			Name:            "No status event",
			GVK:             gvk,
			ReconcilePeriod: 5 * time.Second,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
					"status": map[string]interface{}{
						"conditions": []interface{}{
							map[string]interface{}{
								"status": "True",
								"type":   "Running",
								"ansibleResult": map[string]interface{}{
									"changed":    int64(0),
									"failures":   int64(0),
									"ok":         int64(0),
									"skipped":    int64(0),
									"completion": eventTime.Format("2006-01-02T15:04:05.99999999+00:00"),
								},
								"message": "Failed to get ansible-runner stdout",
							},
						},
					},
				},
			}, true),
			Result: reconcile.Result{
				RequeueAfter: 5 * time.Second,
			},
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
			ShouldError: true,
		},
		{
			Name:            "no manage status",
			GVK:             gvk,
			ReconcilePeriod: 5 * time.Second,
			ManageStatus:    false,
			Runner: &fake.Runner{
				JobEvents: []eventapi.JobEvent{
					{
						Event:   eventapi.EventPlaybookOnStats,
						Created: eventapi.EventTime{Time: eventTime},
					},
				},
			},
			Client: getFakeClientFromObject(&unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
				},
			}, false),
			Result: reconcile.Result{
				RequeueAfter: 5 * time.Second,
			},
			Request: reconcile.Request{
				NamespacedName: types.NamespacedName{
					Name:      "reconcile",
					Namespace: "default",
				},
			},
			ExpectedObject: &unstructured.Unstructured{
				Object: map[string]interface{}{
					"metadata": map[string]interface{}{
						"name":      "reconcile",
						"namespace": "default",
					},
					"apiVersion": "operator-sdk/v1beta1",
					"kind":       "Testing",
					"spec":       map[string]interface{}{},
					"status":     map[string]interface{}{},
				},
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.Name, func(t *testing.T) {
			var aor reconcile.Reconciler = &controller.AnsibleOperatorReconciler{
				GVK:             tc.GVK,
				Runner:          tc.Runner,
				Client:          tc.Client,
				APIReader:       tc.Client,
				EventHandlers:   tc.EventHandlers,
				ReconcilePeriod: tc.ReconcilePeriod,
				ManageStatus:    tc.ManageStatus,
			}
			result, err := aor.Reconcile(context.TODO(), tc.Request)
			if err != nil && !tc.ShouldError {
				t.Fatalf("Unexpected error: %v", err)
			}
			if !reflect.DeepEqual(result, tc.Result) {
				t.Fatalf("Reconcile result does not equal\nexpected: %#v\nactual: %#v", tc.Result, result)
			}
			if tc.ExpectedObject != nil {
				actualObject := &unstructured.Unstructured{}
				actualObject.SetGroupVersionKind(tc.ExpectedObject.GroupVersionKind())
				err := tc.Client.Get(context.TODO(), types.NamespacedName{
					Name:      tc.ExpectedObject.GetName(),
					Namespace: tc.ExpectedObject.GetNamespace(),
				}, actualObject)
				if err != nil {
					t.Fatalf("Failed to get object: (%v)", err)
				}
				if !reflect.DeepEqual(actualObject.GetAnnotations(), tc.ExpectedObject.GetAnnotations()) {
					t.Fatalf("Annotations are not the same\nexpected: %v\nactual: %v",
						tc.ExpectedObject.GetAnnotations(), actualObject.GetAnnotations())
				}
				if !reflect.DeepEqual(actualObject.GetFinalizers(), tc.ExpectedObject.GetFinalizers()) &&
					len(actualObject.GetFinalizers()) != 0 && len(tc.ExpectedObject.GetFinalizers()) != 0 {
					t.Fatalf("Finalizers are not the same\nexpected: %#v\nactual: %#v",
						tc.ExpectedObject.GetFinalizers(), actualObject.GetFinalizers())
				}
				sMap, _ := tc.ExpectedObject.Object["status"].(map[string]interface{})
				expectedStatus := ansiblestatus.CreateFromMap(sMap)
				sMap, _ = actualObject.Object["status"].(map[string]interface{})
				actualStatus := ansiblestatus.CreateFromMap(sMap)
				if len(expectedStatus.Conditions) != len(actualStatus.Conditions) {
					t.Fatalf("Status conditions not the same\nexpected: %v\nactual: %v", expectedStatus,
						actualStatus)
				}
				for _, c := range expectedStatus.Conditions {
					actualCond := ansiblestatus.GetCondition(actualStatus, c.Type)
					if c.Reason != actualCond.Reason || c.Message != actualCond.Message || c.Status !=
						actualCond.Status {
						t.Fatalf("Message or reason did not match\nexpected: %+v\nactual: %+v", c, actualCond)
					}
					if c.AnsibleResult == nil && actualCond.AnsibleResult != nil {
						t.Fatalf("Ansible result did not match\nexpected: %+v\nactual: %+v", c.AnsibleResult,
							actualCond.AnsibleResult)
					}
					if c.AnsibleResult != nil {
						if !reflect.DeepEqual(c.AnsibleResult, actualCond.AnsibleResult) {
							t.Fatalf("Ansible result did not match\nexpected: %+v\nactual: %+v", c.AnsibleResult,
								actualCond.AnsibleResult)
						}
					}
				}
			}
		})
	}
}

// Tech Debt: If we continue to use fake client, convert "reconcile" into a typed object for
// testing to identify the status sub resource.
//
// getFakeClientFromObject creates a fake client with the unstructured object added to the
// tracker.
func getFakeClientFromObject(obj *unstructured.Unstructured, withStatus bool) client.Client {
	if withStatus {
		return fakeclient.NewClientBuilder().WithStatusSubresource(obj).WithObjects(obj).Build()
	}
	return fakeclient.NewClientBuilder().WithObjects(obj).Build()
}
