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

// This code was retrieved from
// https://github.com/kubernetes/apiserver/blob/master/pkg/endpoints/request/requestinfo.go
// and slightly modified for use in this project

package requestfactory

import (
	"fmt"
	"net/http"
	"strings"

	"k8s.io/apimachinery/pkg/api/validation/path"
	metainternalversion "k8s.io/apimachinery/pkg/apis/meta/internalversion"
	metainternalscheme "k8s.io/apimachinery/pkg/apis/meta/internalversion/scheme"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/utils/set"

	logf "sigs.k8s.io/controller-runtime/pkg/log"
)

var log = logf.Log.WithName("requestfactory")

// RequestInfo holds information parsed from the http.Request
type RequestInfo struct {
	// IsResourceRequest indicates whether or not the request is for an API
	// resource or subresource
	IsResourceRequest bool
	// Path is the URL path of the request
	Path string
	// Verb is the kube verb associated with the request for API requests, not
	// the http verb.  This includes things like list and watch.  for
	// non-resource requests, this is the lowercase http verb
	Verb string

	APIPrefix  string
	APIGroup   string
	APIVersion string
	Namespace  string
	// Resource is the name of the resource being requested.  This is not the
	// kind.  For example: pods
	Resource string
	// Subresource is the name of the subresource being requested.  This is a
	// different resource, scoped to the parent resource, but it may have a
	// different kind.  For instance, /pods has the resource "pods" and the kind
	// "Pod", while /pods/foo/status has the resource "pods", the sub resource
	// "status", and the kind "Pod" (because status operates on pods). The
	// binding resource for a pod though may be /pods/foo/binding, which has
	// resource "pods", subresource "binding", and kind "Binding".
	Subresource string
	// Name is empty for some verbs, but if the request directly indicates a name
	// (not in body content) then this field is filled in.
	Name string
	// Parts are the path parts for the request, always starting with
	// /{resource}/{name}
	Parts []string
}

// specialVerbs contains just strings which are used in REST paths for special
// actions that don't fall under the normal CRUDdy GET/POST/PUT/DELETE actions
// on REST objects.  TODO: find a way to keep this up to date automatically.
// Maybe dynamically populate list as handlers added to master's Mux.
var specialVerbs = set.New("proxy", "watch")

// specialVerbsNoSubresources contains root verbs which do not allow
// subresources
var specialVerbsNoSubresources = set.New("proxy")

// namespaceSubresources contains subresources of namespace this list allows
// the parser to distinguish between a namespace subresource, and a namespaced
// resource
var namespaceSubresources = set.New("status", "finalize")

// NamespaceSubResourcesForTest exports namespaceSubresources for testing in
// pkg/master/master_test.go, so we never drift
var NamespaceSubResourcesForTest = set.New(namespaceSubresources.SortedList()...)

type RequestInfoFactory struct {
	APIPrefixes          set.Set[string] // without leading and trailing slashes
	GrouplessAPIPrefixes set.Set[string] // without leading and trailing slashes
}

// TODO write an integration test against the swagger doc to test the
// RequestInfo and match up behavior to responses NewRequestInfo returns the
// information from the http request.  If error is not nil, RequestInfo holds
// the information as best it is known before the failure It handles both
// resource and non-resource requests and fills in all the pertinent
// information for each.
// Valid Inputs:
// Resource paths
// /apis/{api-group}/{version}/namespaces
// /api/{version}/namespaces
// /api/{version}/namespaces/{namespace}
// /api/{version}/namespaces/{namespace}/{resource}
// /api/{version}/namespaces/{namespace}/{resource}/{resourceName}
// /api/{version}/{resource}
// /api/{version}/{resource}/{resourceName}
//
// Special verbs without subresources:
// /api/{version}/proxy/{resource}/{resourceName}
// /api/{version}/proxy/namespaces/{namespace}/{resource}/{resourceName}
//
// Special verbs with subresources:
// /api/{version}/watch/{resource}
// /api/{version}/watch/namespaces/{namespace}/{resource}
//
// NonResource paths
// /apis/{api-group}/{version}
// /apis/{api-group}
// /apis
// /api/{version}
// /api
// /healthz

func (r *RequestInfoFactory) NewRequestInfo(req *http.Request) (*RequestInfo, error) { //nolint:gocyclo
	// TODO: Try to reduce the complexity of this last measured at 33 (failing at > 30) and remove the // nolint:gocyclo
	// start with a non-resource request until proven otherwise
	requestInfo := RequestInfo{
		IsResourceRequest: false,
		Path:              req.URL.Path,
		Verb:              strings.ToLower(req.Method),
	}

	currentParts := splitPath(req.URL.Path)
	if len(currentParts) < 3 {
		// return a non-resource request
		return &requestInfo, nil
	}

	if !r.APIPrefixes.Has(currentParts[0]) {
		// return a non-resource request
		return &requestInfo, nil
	}
	requestInfo.APIPrefix = currentParts[0]
	currentParts = currentParts[1:]

	if !r.GrouplessAPIPrefixes.Has(requestInfo.APIPrefix) {
		// one part (APIPrefix) has already been consumed, so this is actually "do
		// we have four parts?"
		if len(currentParts) < 3 {
			// return a non-resource request
			return &requestInfo, nil
		}

		requestInfo.APIGroup = currentParts[0]
		currentParts = currentParts[1:]
	}

	requestInfo.IsResourceRequest = true
	requestInfo.APIVersion = currentParts[0]
	currentParts = currentParts[1:]

	// handle input of form /{specialVerb}/*
	if specialVerbs.Has(currentParts[0]) {
		if len(currentParts) < 2 {
			return &requestInfo, fmt.Errorf("unable to determine kind and namespace from url, %v", req.URL)
		}

		requestInfo.Verb = currentParts[0]
		currentParts = currentParts[1:]
	} else {
		switch req.Method {
		case "POST":
			requestInfo.Verb = "create"
		case "GET", "HEAD":
			requestInfo.Verb = "get"
		case "PUT":
			requestInfo.Verb = "update"
		case "PATCH":
			requestInfo.Verb = "patch"
		case "DELETE":
			requestInfo.Verb = "delete"
		default:
			requestInfo.Verb = ""
		}
	}

	// URL forms: /namespaces/{namespace}/{kind}/*, where parts are adjusted to
	// be relative to kind
	if currentParts[0] == "namespaces" {
		if len(currentParts) > 1 {
			requestInfo.Namespace = currentParts[1]

			// if there is another step after the namespace name and it is not a
			// known namespace subresource move currentParts to include it as a
			// resource in its own right
			if len(currentParts) > 2 && !namespaceSubresources.Has(currentParts[2]) {
				currentParts = currentParts[2:]
			}
		}
	} else {
		requestInfo.Namespace = metav1.NamespaceNone
	}

	// parsing successful, so we now know the proper value for .Parts
	requestInfo.Parts = currentParts

	// parts look like:
	// resource/resourceName/subresource/other/stuff/we/don't/interpret
	switch {
	case len(requestInfo.Parts) >= 3 && !specialVerbsNoSubresources.Has(requestInfo.Verb):
		requestInfo.Subresource = requestInfo.Parts[2]
		fallthrough
	case len(requestInfo.Parts) >= 2:
		requestInfo.Name = requestInfo.Parts[1]
		fallthrough
	case len(requestInfo.Parts) >= 1:
		requestInfo.Resource = requestInfo.Parts[0]
	}

	// if there's no name on the request and we thought it was a get before, then
	// the actual verb is a list or a watch
	if len(requestInfo.Name) == 0 && requestInfo.Verb == "get" {
		opts := metainternalversion.ListOptions{}
		if err := metainternalscheme.ParameterCodec.DecodeParameters(req.URL.Query(), metav1.SchemeGroupVersion,
			&opts); err != nil {
			// An error in parsing request will result in default to "list" and not
			// setting "name" field.
			log.Error(err, "Could not parse request")
			// Reset opts to not rely on partial results from parsing.
			// However, if watch is set, let's report it.
			opts = metainternalversion.ListOptions{}
			if values := req.URL.Query()["watch"]; len(values) > 0 {
				switch strings.ToLower(values[0]) {
				case "false", "0":
				default:
					opts.Watch = true
				}
			}
		}

		if opts.Watch {
			requestInfo.Verb = "watch"
		} else {
			requestInfo.Verb = "list"
		}

		if opts.FieldSelector != nil {
			if name, ok := opts.FieldSelector.RequiresExactMatch("metadata.name"); ok {
				if len(path.IsValidPathSegmentName(name)) == 0 {
					requestInfo.Name = name
				}
			}
		}
	}
	// if there's no name on the request and we thought it was a delete before,
	// then the actual verb is deletecollection
	if len(requestInfo.Name) == 0 && requestInfo.Verb == "delete" {
		requestInfo.Verb = "deletecollection"
	}

	return &requestInfo, nil
}

// splitPath returns the segments for a URL path.
func splitPath(path string) []string {
	path = strings.Trim(path, "/")
	if path == "" {
		return []string{}
	}
	return strings.Split(path, "/")
}
