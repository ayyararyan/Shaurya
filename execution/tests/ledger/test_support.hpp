#pragma once
#include "shaurya/execution/contracts.hpp"
#include <filesystem>
#include <iostream>
#include <string_view>
#include <unistd.h>
inline void require_test(bool condition,std::string_view message){if(!condition){std::cerr<<message<<'\n';std::exit(1);}}
inline std::filesystem::path test_directory(std::string_view name){auto path=std::filesystem::path("/private/tmp")/(std::string("shaurya-")+std::string(name)+"-"+std::to_string(::getpid()));std::filesystem::remove_all(path);std::filesystem::create_directory(path);std::filesystem::permissions(path,std::filesystem::perms::owner_all,std::filesystem::perm_options::replace);return path;}
inline shaurya::execution::ExecutionEvent event(std::string id,std::string type,shaurya::execution::JsonObject payload={},std::optional<std::string> intent=std::nullopt,std::optional<std::string> order=std::nullopt){const bool correlated=intent.has_value();return {std::move(id),std::move(type),100,"00000000-0000-4000-8000-000000000003",correlated?std::optional<std::string>("d51"):std::nullopt,correlated?std::optional<std::string>("00000000-0000-4000-8000-000000000002"):std::nullopt,std::move(intent),std::move(order),std::move(payload)};}
