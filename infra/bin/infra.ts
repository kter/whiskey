#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { buildApp } from '../lib/app-builder';

buildApp(new cdk.App());
